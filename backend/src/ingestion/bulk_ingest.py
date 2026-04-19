"""
SAM.gov Bulk Ingestion Pipeline
--------------------------------
Downloads opportunities from SAM.gov in paginated batches and upserts
them into Supabase. Designed to run two ways:

  1. Full load  — python bulk_ingest.py --full
     Downloads all active opportunities posted in the last 365 days.
     Run once on initial setup. Takes ~30-60 minutes depending on volume.

  2. Delta load — python bulk_ingest.py --delta
     Downloads only records modified since the last successful run.
     Run nightly via cron / APScheduler.
"""

import os
import sys
import json
import logging
import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from the project root (two levels up from this file)
env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SAM_API_BASE = "https://api.sam.gov/opportunities/v2/search"
BATCH_SIZE = 1000       # SAM.gov max per page
UPSERT_BATCH = 250      # rows per Supabase upsert call
LAST_RUN_FILE = Path(__file__).resolve().parents[3] / "data" / "last_ingest.txt"


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(url, key)


def get_sam_api_key() -> str:
    key = os.getenv("SAM_API_KEY", "")
    if not key:
        raise RuntimeError("SAM_API_KEY must be set in .env")
    return key


# ---------------------------------------------------------------------------
# SAM.gov fetching
# ---------------------------------------------------------------------------

def fetch_page(api_key: str, params: dict, attempt: int = 1) -> dict | None:
    """Fetch a single page from SAM.gov with retry logic."""
    try:
        resp = requests.get(SAM_API_BASE, params=params, timeout=30)

        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            logger.warning(f"Rate limited. Waiting {wait}s...")
            time.sleep(wait)
            return fetch_page(api_key, params, attempt)

        resp.raise_for_status()
        return resp.json()

    except requests.RequestException as e:
        if attempt < 3:
            wait = 2 ** attempt
            logger.warning(f"Request failed ({e}). Retrying in {wait}s...")
            time.sleep(wait)
            return fetch_page(api_key, params, attempt + 1)
        logger.error(f"All retries exhausted: {e}")
        return None


def fetch_all_opportunities(api_key: str, posted_from: str, posted_to: str, modified_from: str = None) -> list[dict]:
    """
    Page through the SAM.gov API and return all raw opportunity records.
    posted_from / posted_to: date range for initial posted date (MM/DD/YYYY)
    modified_from: if set, only fetch records modified after this date (delta mode)
    """
    params = {
        "api_key": api_key,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "limit": BATCH_SIZE,
        "offset": 0,
        "active": "true",
    }

    if modified_from:
        params["modifiedFrom"] = modified_from

    logger.info(f"Fetching SAM.gov opportunities: {posted_from} → {posted_to}" +
                (f" (modified since {modified_from})" if modified_from else ""))

    first_page = fetch_page(api_key, params)
    if not first_page:
        return []

    total = first_page.get("totalRecords", 0)
    records = first_page.get("opportunitiesData", [])
    logger.info(f"Total records available: {total:,}")

    while len(records) < total:
        params["offset"] = len(records)
        logger.info(f"Fetching offset {len(records):,} / {total:,}...")
        page = fetch_page(api_key, params)
        if not page or not page.get("opportunitiesData"):
            logger.warning("Empty page returned — stopping pagination")
            break
        records.extend(page["opportunitiesData"])
        # Be polite to the API
        time.sleep(0.5)

    logger.info(f"Fetched {len(records):,} records from SAM.gov")
    return records


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_opportunity(raw: dict) -> dict:
    """Transform a raw SAM.gov API record into our database schema."""

    # Agency: use full parent path, fall back to department
    full_path = raw.get("fullParentPathName", "") or ""
    parts = [p.strip() for p in full_path.split(".") if p.strip()]
    agency = parts[0] if parts else raw.get("department", "")
    sub_agency = parts[1] if len(parts) > 1 else ""
    office = parts[-1] if len(parts) > 2 else ""

    # Place of performance
    pop = raw.get("placeOfPerformance", {}) or {}
    pop_state = ""
    pop_city = ""
    if isinstance(pop, dict):
        state_obj = pop.get("state", {}) or {}
        pop_state = state_obj.get("code", "") if isinstance(state_obj, dict) else ""
        city_obj = pop.get("city", {}) or {}
        pop_city = city_obj.get("name", "") if isinstance(city_obj, dict) else ""

    # Value — award amount if available
    value_max = None
    award = raw.get("award", {}) or {}
    if isinstance(award, dict) and award.get("amount"):
        try:
            value_max = float(str(award["amount"]).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

    # Attachments
    attachments = []
    for link in (raw.get("resourceLinks") or []):
        if isinstance(link, str) and link.strip():
            attachments.append({"url": link, "filename": link.split("/")[-1]})

    # Notice type normalization
    notice_type_raw = (raw.get("type") or "").lower()
    notice_type_map = {
        "o": "solicitation",
        "p": "presolicitation",
        "k": "combined",
        "r": "sources_sought",
        "s": "special",
        "g": "sale_of_surplus",
        "i": "intent_to_bundle",
        "a": "award",
        "j": "justification",
        "m": "modification",
        "u": "justification",
        "f": "foreign_government",
    }
    notice_type = notice_type_map.get(notice_type_raw, notice_type_raw or "solicitation")

    # Set-aside
    set_aside = raw.get("typeOfSetAside") or raw.get("typeOfSetAsideDescription") or ""

    # Dates
    def parse_date(val):
        if not val:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
            try:
                dt = datetime.strptime(str(val)[:19], fmt[:len(str(val)[:19])])
                return dt.isoformat()
            except ValueError:
                continue
        return None

    description = raw.get("description") or raw.get("additionalInfoLink") or ""

    return {
        "notice_id": raw.get("noticeId", ""),
        "solicitation_number": raw.get("solicitationNumber") or raw.get("solNum") or "",
        "title": raw.get("title", "") or "",
        "description": description,
        "ai_summary": None,        # Generated separately on-demand
        "agency": agency,
        "sub_agency": sub_agency,
        "office": office,
        "naics_code": raw.get("naicsCode") or "",
        "psc_code": raw.get("classificationCode") or "",
        "set_aside_type": set_aside,
        "contract_type": raw.get("contractType") or "",
        "notice_type": notice_type,
        "value_min": None,
        "value_max": value_max,
        "pop_city": pop_city,
        "pop_state": pop_state,
        "pop_country": "USA",
        "posted_date": parse_date(raw.get("postedDate")),
        "response_deadline": parse_date(raw.get("responseDeadLine")),
        "modified_date": parse_date(raw.get("modifiedDate")),
        "status": "active",
        "source": "sam_gov",
        "attachments": json.dumps(attachments),
        "raw_data": json.dumps(raw),
    }


# ---------------------------------------------------------------------------
# Supabase upsert
# ---------------------------------------------------------------------------

def upsert_batch(supabase: Client, rows: list[dict]) -> int:
    """Upsert a batch of parsed opportunities. Returns number of rows written."""
    if not rows:
        return 0
    try:
        supabase.table("opportunities").upsert(
            rows,
            on_conflict="notice_id"
        ).execute()
        return len(rows)
    except Exception as e:
        logger.error(f"Upsert failed: {e}")
        return 0


def upsert_all(supabase: Client, parsed: list[dict]) -> int:
    """Upsert all parsed records in chunks."""
    total_written = 0
    for i in range(0, len(parsed), UPSERT_BATCH):
        chunk = parsed[i: i + UPSERT_BATCH]
        written = upsert_batch(supabase, chunk)
        total_written += written
        logger.info(f"Upserted {total_written:,} / {len(parsed):,} records...")
    return total_written


# ---------------------------------------------------------------------------
# Last-run tracking
# ---------------------------------------------------------------------------

def read_last_run() -> str | None:
    """Return the ISO timestamp of the last successful ingest, or None."""
    if LAST_RUN_FILE.exists():
        val = LAST_RUN_FILE.read_text().strip()
        return val if val else None
    return None


def write_last_run():
    """Record the current UTC time as the last successful ingest."""
    LAST_RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_FILE.write_text(datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_full_load():
    """
    Download all active opportunities posted in the last 365 days.
    Run once on initial setup.
    """
    logger.info("=== FULL LOAD starting ===")
    supabase = get_supabase()
    api_key = get_sam_api_key()

    today = datetime.now()
    posted_to = today.strftime("%m/%d/%Y")
    posted_from = (today - timedelta(days=365)).strftime("%m/%d/%Y")

    raw_records = fetch_all_opportunities(api_key, posted_from, posted_to)
    if not raw_records:
        logger.error("No records fetched. Check your SAM_API_KEY and network.")
        return

    logger.info(f"Parsing {len(raw_records):,} records...")
    # Filter out records with no notice_id (malformed)
    parsed = [parse_opportunity(r) for r in raw_records if r.get("noticeId")]

    logger.info(f"Upserting {len(parsed):,} records to Supabase...")
    written = upsert_all(supabase, parsed)

    write_last_run()
    logger.info(f"=== FULL LOAD complete: {written:,} records written ===")


def run_delta_load():
    """
    Download only records modified since the last successful run.
    Run nightly.
    """
    logger.info("=== DELTA LOAD starting ===")
    supabase = get_supabase()
    api_key = get_sam_api_key()

    last_run = read_last_run()
    if not last_run:
        logger.warning("No last run timestamp found. Running full load instead.")
        run_full_load()
        return

    last_run_dt = datetime.fromisoformat(last_run)
    modified_from = last_run_dt.strftime("%m/%d/%Y")

    today = datetime.now()
    posted_to = today.strftime("%m/%d/%Y")
    posted_from = (today - timedelta(days=365)).strftime("%m/%d/%Y")

    logger.info(f"Fetching records modified since {modified_from}")
    raw_records = fetch_all_opportunities(
        api_key, posted_from, posted_to, modified_from=modified_from
    )

    if not raw_records:
        logger.info("No new or modified records since last run.")
        write_last_run()
        return

    parsed = [parse_opportunity(r) for r in raw_records if r.get("noticeId")]
    written = upsert_all(supabase, parsed)

    write_last_run()
    logger.info(f"=== DELTA LOAD complete: {written:,} records written ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM.gov bulk ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full", action="store_true", help="Full load: all opportunities from past 365 days")
    group.add_argument("--delta", action="store_true", help="Delta load: only records modified since last run")
    args = parser.parse_args()

    if args.full:
        run_full_load()
    elif args.delta:
        run_delta_load()
