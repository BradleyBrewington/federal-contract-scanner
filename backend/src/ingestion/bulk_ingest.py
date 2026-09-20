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
import re
import json
import html as html_lib
import logging
import argparse
import threading
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv
from supabase import create_client, Client

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

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
SAM_DESC_BASE = "https://api.sam.gov/prod/opportunities/v1/noticedesc"
BATCH_SIZE        = 1000      # SAM.gov max per page
UPSERT_BATCH      = 250       # rows per Supabase upsert call
DESC_WORKERS      = 2         # parallel description fetches — bump to 4 if no 429s observed
DESC_WORKER_SLEEP = 0.5       # seconds to sleep after each fetch per worker (~1 req/s total)
DESC_MAX_CHARS    = 50_000    # store up to 50k chars of description text
DESC_DAILY_CAP    = 800       # conservative cap for noticedesc endpoint (~1,000 actual daily limit)
DATA_DIR      = Path(__file__).resolve().parents[3] / "data"
LAST_RUN_FILE = DATA_DIR / "last_ingest.txt"


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
# Description fetching
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """
    Remove HTML tags, decode entities, normalize whitespace, strip Postgres-incompatible
    control characters. Uses BeautifulSoup when available (handles MS Word HTML, tables,
    embedded images); falls back to regex for environments without bs4.
    """
    if _HAS_BS4:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(separator=' ', strip=True)
        except Exception:
            text = re.sub(r'<[^>]+>', ' ', text)
    else:
        text = re.sub(r'<[^>]+>', ' ', text)

    # Decode HTML entities (&amp; &#39; &nbsp; etc.) that survive tag stripping
    text = html_lib.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove null bytes and other control characters Postgres rejects
    # (keep \t \n \r which are valid in text columns)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text


# Phrases that indicate a notice was cancelled/withdrawn/superseded.
# If found, update record status rather than writing the text as a description.
_WITHDRAWN_PHRASES = [
    "this notice has been cancelled",
    "this notice has been withdrawn",
    "this notice has been replaced",
    "this solicitation has been cancelled",
    "this requirement has been cancelled",
    "award has been cancelled",
]

_SEE_ATTACHMENT_PHRASES = [
    "see attach", "see the attach", "refer to attach",
    "see sow", "see the sow", "see statement of work",
    "see enclosed", "attached herein", "see solicitation",
    "see rfp", "see rfi", "see rfq",
    "please see", "refer to document", "see document",
    "see associated file", "see below for", "see amendment",
    "see pwd", "see performance work statement", "see pws",
]


def _is_see_attachment(text: str) -> bool:
    """
    Returns True if the fetched description is just a pointer to an attachment,
    not substantive scope text. Descriptions this short with these phrases
    contribute nothing to scoring or display — skip writing them to the DB.
    Long descriptions (>600 chars) are assumed real even if they contain these
    phrases incidentally.
    """
    if not text or len(text) > 600:
        return False
    lowered = text.lower()
    return any(phrase in lowered for phrase in _SEE_ATTACHMENT_PHRASES)


def fetch_description(notice_id: str, api_key: str) -> tuple[str | None, int | None]:
    """
    Fetch the full description text for a SAM.gov notice.

    Returns (text, http_status):
      (str, 200)   — real description text; save to DB
      ("", 404)    — SAM.gov has no description for this notice; normal, not an error
      (None, 429)  — rate limited; caller should back off and may abort
      (None, 5xx)  — server error; retried once with 30s sleep before returning
      (None, None) — connection exception

    429 and 5xx get one automatic retry with exponential sleep before returning failure.
    """
    if not notice_id:
        return "", 404

    def _do_request():
        return requests.get(
            SAM_DESC_BASE,
            params={"noticeid": notice_id, "api_key": api_key},
            timeout=15,
        )

    try:
        resp = _do_request()

        # 429 — daily quota exhausted; do not retry (30s sleep doesn't help)
        if resp.status_code == 429:
            logger.warning(f"429 on {notice_id} — quota exhausted, aborting record")
            return None, 429

        # 5xx — transient server error: sleep 10s and retry once
        if resp.status_code >= 500:
            logger.warning(f"HTTP {resp.status_code} on {notice_id} — sleeping 10s then retrying")
            time.sleep(10)
            try:
                resp = _do_request()
            except Exception:
                return None, resp.status_code
            if resp.status_code >= 500:
                return None, resp.status_code

        if resp.status_code == 404:
            return "", 404

        if resp.status_code != 200:
            logger.debug(f"fetch_description {notice_id}: HTTP {resp.status_code} — {resp.text[:200]}")
            return None, resp.status_code

        data = resp.json()
        if isinstance(data, list):
            parts = [item.get("description") or item.get("body") or "" for item in data]
            raw = " ".join(p for p in parts if p)
        else:
            raw = data.get("description") or data.get("body") or ""

        if not raw:
            logger.debug(f"fetch_description {notice_id}: 200 OK but empty body")
            return "", 200

        return _strip_html(raw)[:DESC_MAX_CHARS], 200

    except Exception as e:
        logger.debug(f"fetch_description {notice_id}: exception — {e}")
        return None, None


def enrich_descriptions(parsed_records: list[dict], api_key: str) -> list[dict]:
    """
    For any record whose description field is a URL (not real text), fetch the
    actual description text from SAM.gov and replace it in-place.

    Uses a thread pool so the full delta batch is enriched in parallel.
    Records whose fetch fails are left with their original URL value so the
    serve-time fallback in v2.py can retry on first load.
    """
    url_records = [r for r in parsed_records if (r.get("description") or "").startswith("http")]
    if not url_records:
        return parsed_records

    logger.info(f"Fetching descriptions for {len(url_records)} records ({DESC_WORKERS} workers)...")
    fetched = 0
    failed  = 0

    def _fetch(record):
        text, _status = fetch_description(record.get("notice_id", ""), api_key)
        return record["notice_id"], text

    with ThreadPoolExecutor(max_workers=DESC_WORKERS) as pool:
        futures = {pool.submit(_fetch, r): r for r in url_records}
        for future in as_completed(futures):
            notice_id, text = future.result()
            if text:
                for r in parsed_records:
                    if r.get("notice_id") == notice_id:
                        r["description"] = text
                        break
                fetched += 1
            else:
                failed += 1

    logger.info(f"Description enrichment: {fetched} fetched, {failed} failed/skipped")
    return parsed_records


# ---------------------------------------------------------------------------
# SAM.gov fetching
# ---------------------------------------------------------------------------

def fetch_page(api_key: str, params: dict, attempt: int = 1) -> dict | None:
    """Fetch a single page from SAM.gov with retry logic."""
    try:
        resp = requests.get(SAM_API_BASE, params=params, timeout=30)

        if resp.status_code == 429:
            # Retry-After can be an integer (seconds) or an HTTP date string.
            # e.g. "60" vs "Fri, 01 May 2026 00:00:00 GMT"
            retry_after = resp.headers.get("Retry-After", "60")
            try:
                wait = int(retry_after)
            except ValueError:
                # HTTP date format — compute seconds until that time
                from email.utils import parsedate_to_datetime
                try:
                    until = parsedate_to_datetime(retry_after)
                    wait = max(60, int((until - datetime.now(timezone.utc)).total_seconds()))
                except Exception:
                    wait = 60
            logger.warning(f"Rate limited. Retry-After: {retry_after!r} — waiting {wait}s...")
            if wait > 300:
                # Quota exhausted for the day — don't sleep for hours, just abort
                logger.error(
                    f"SAM.gov quota exhausted until {retry_after}. "
                    "Re-run after midnight UTC. Aborting."
                )
                return None
            time.sleep(wait)
            return fetch_page(api_key, params, attempt)

        resp.raise_for_status()
        return resp.json()

    except requests.RequestException as e:
        if attempt < 5:
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
    }

    if modified_from:
        params["modifiedFrom"] = modified_from

    logger.info(f"Fetching SAM.gov opportunities: {posted_from} -> {posted_to}" +
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
        "status": "active" if raw.get("active", "Yes") == "Yes" else "expired",
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
    Download all opportunities posted in the last 12 months.
    Uses two 6-month windows — SAM.gov rejects ranges exceeding ~180 days
    when they cross a calendar year boundary.
    Run once on initial setup.
    """
    logger.info("=== FULL LOAD starting ===")
    supabase = get_supabase()
    api_key = get_sam_api_key()

    today = datetime.now()
    all_raw = []

    # Window 1: last 6 months
    w1_to = today
    w1_from = today - timedelta(days=180)
    logger.info("Fetching window 1: last 6 months")
    batch1 = fetch_all_opportunities(
        api_key,
        w1_from.strftime("%m/%d/%Y"),
        w1_to.strftime("%m/%d/%Y"),
    )
    all_raw.extend(batch1)
    logger.info(f"Window 1: {len(batch1):,} records")

    # Window 2: 6–12 months ago
    w2_to = today - timedelta(days=181)
    w2_from = today - timedelta(days=365)
    logger.info("Fetching window 2: 6–12 months ago")
    batch2 = fetch_all_opportunities(
        api_key,
        w2_from.strftime("%m/%d/%Y"),
        w2_to.strftime("%m/%d/%Y"),
    )
    all_raw.extend(batch2)
    logger.info(f"Window 2: {len(batch2):,} records")

    if not all_raw:
        logger.error("No records fetched. Check your SAM_API_KEY and network.")
        return

    logger.info(f"Total fetched: {len(all_raw):,} records across both windows")
    parsed = [parse_opportunity(r) for r in all_raw if r.get("noticeId")]

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
    posted_from = (today - timedelta(days=180)).strftime("%m/%d/%Y")  # 6-month window max

    logger.info(f"Fetching records modified since {modified_from}")
    raw_records = fetch_all_opportunities(
        api_key, posted_from, posted_to, modified_from=modified_from
    )

    if not raw_records:
        logger.info("No new or modified records since last run.")
        write_last_run()
        return

    parsed = [parse_opportunity(r) for r in raw_records if r.get("noticeId")]

    # Descriptions are now handled by daily CSV ingest — see csv_ingest.py.
    # enrich_descriptions() is retained for attachment downloads and see-attached
    # records only; it is not called here on the normal delta path.

    written = upsert_all(supabase, parsed)

    write_last_run()
    logger.info(f"=== DELTA LOAD complete: {written:,} records written ===")


if __name__ == "__main__":
    from csv_ingest import run_csv_ingest, validate_csv_descriptions, load_csv_duckdb, CSV_URL

    parser = argparse.ArgumentParser(description="SAM.gov bulk ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full",  action="store_true", help="Full load: all opportunities from past 365 days")
    group.add_argument("--delta", action="store_true", help="Delta load: only records modified since last run")
    group.add_argument("--csv-ingest", action="store_true",
                       help="Daily CSV ingest: load descriptions from GSA public extract (s3.amazonaws.com/falextracts/...)")
    group.add_argument("--validate-csv", action="store_true",
                       help="Validate CSV descriptions against existing API-sourced DB records before cutover")
    args = parser.parse_args()

    if args.full:
        run_full_load()
    elif args.delta:
        run_delta_load()
    elif args.csv_ingest:
        stats = run_csv_ingest()
        logger.info(f"CSV ingest stats: {stats}")
    elif args.validate_csv:
        logger.info("Loading CSV for validation...")
        raw_rows = load_csv_duckdb(CSV_URL)
        logger.info(f"Loaded {len(raw_rows):,} rows from CSV")
        passed = validate_csv_descriptions(raw_rows)
        sys.exit(0 if passed else 1)
