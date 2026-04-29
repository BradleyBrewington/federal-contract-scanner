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
DESC_DAILY_CAP    = 9_000     # stop backfill at this many fetches/day; leaves headroom for delta + search
SANITY_CHECK_N         = 20   # records to probe before starting main run (issue #1)
SANITY_FAIL_THRESHOLD  = 0.20 # abort sanity if >20% return None (issue #1)
ABORT_FAIL_THRESHOLD   = 0.05 # abort mid-run if rolling failure rate exceeds 5% (issue #8)
RATE_LIMIT_ABORT_COUNT = 5    # shut down if this many 429s accumulate across all workers (issue #2)
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

        # 429 — rate limited: sleep 30s and retry once
        if resp.status_code == 429:
            logger.warning(f"429 on {notice_id} — sleeping 30s then retrying")
            time.sleep(30)
            try:
                resp = _do_request()
            except Exception:
                return None, 429
            if resp.status_code == 429:
                logger.warning(f"429 again on {notice_id} after retry — aborting this record")
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
            wait = int(resp.headers.get("Retry-After", 60))
            logger.warning(f"Rate limited. Waiting {wait}s...")
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

    # Fetch real description text for any records that only have a SAM.gov URL.
    # Delta batches are typically small (50–500 records) so this adds <1 minute.
    parsed = enrich_descriptions(parsed, api_key)

    written = upsert_all(supabase, parsed)

    write_last_run()
    logger.info(f"=== DELTA LOAD complete: {written:,} records written ===")


def run_backfill_descriptions():
    """
    Resumable backfill: fetch real description text for active DB records whose
    description field is still a SAM.gov API URL.

    Fixes applied:
      #1  Sanity check: 20 records, abort if >20% return None
      #2  Exponential backoff on 429/5xx in fetch_description; abort if 5 total 429s
      #3  Ordering: posted_date DESC (best available without impression tracking)
      #5  see_attachment: notice_ids logged to data/see_attachment_YYYY-MM-DD.txt
      #6  Withdrawn/cancelled detection: updates status column, skips description write
      #7  Persistent log file at data/logs/backfill_YYYY-MM-DD.log
      #8  Mid-run abort if rolling failure rate exceeds 5% after 100 records
      #9  Saves original URL to description_url before overwriting; falls back if column missing
      #10 _strip_html uses BeautifulSoup when available + html.unescape

    Prerequisite schema change (run once in Supabase SQL Editor):
      ALTER TABLE opportunities
        ADD COLUMN IF NOT EXISTS description_url TEXT,
        ADD COLUMN IF NOT EXISTS description_fetched_at TIMESTAMPTZ;

    Run daily until complete:
      py -3 backend/src/ingestion/bulk_ingest.py --backfill-descriptions

    Safe to interrupt and re-run — enriched records no longer match the URL filter.
    """
    run_start = datetime.now(timezone.utc)
    run_date  = run_start.strftime("%Y-%m-%d")

    # ── Persistent log file ─────────────────────────────────────────────────
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / f"backfill_{run_date}.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    logger.info("=== DESCRIPTION BACKFILL starting ===")
    supabase = get_supabase()
    api_key  = get_sam_api_key()

    # ── Quota tracking ──────────────────────────────────────────────────────
    # SAM.gov doesn't expose remaining quota via headers — track client-side.
    quota_file = DATA_DIR / f"quota_{run_date}.json"
    quota_used_today = 0
    if quota_file.exists():
        try:
            quota_used_today = json.loads(quota_file.read_text()).get("used", 0)
        except Exception:
            pass
    quota_available = DESC_DAILY_CAP - quota_used_today
    logger.info(f"Quota used today so far: {quota_used_today:,} / 10,000. Available for this run: {quota_available:,}")
    if quota_available <= 0:
        logger.error("Daily quota already consumed. Re-run after midnight UTC.")
        logger.removeHandler(file_handler)
        return

    # ── Collect work set ────────────────────────────────────────────────────
    # Fetch description field too so we can save it to description_url before overwriting.
    # Active-only: expired records never surface in the feed.
    # posted_date DESC: most recently posted = most likely to appear in feed.
    all_stubs = []
    offset    = 0
    page_size = 1000
    while True:
        batch = (
            supabase.table("opportunities")
            .select("id, notice_id, description")
            .eq("status", "active")
            .ilike("description", "http%")
            .order("posted_date", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = batch.data or []
        if not rows:
            break
        all_stubs.extend(rows)
        logger.info(f"Found {len(all_stubs):,} active URL-description records so far...")
        if len(rows) < page_size:
            break
        offset += page_size

    if not all_stubs:
        logger.info("No active URL-description records found — backfill complete.")
        logger.removeHandler(file_handler)
        return

    capped   = len(all_stubs) > quota_available
    work_set = all_stubs[:quota_available]
    logger.info(
        f"{'Capping at quota' if capped else 'Processing'} {len(work_set):,} of "
        f"{len(all_stubs):,} records (workers: {DESC_WORKERS})"
    )
    if capped:
        logger.info(f"Re-run tomorrow for the remaining {len(all_stubs) - quota_available:,} records.")

    # ── Sanity check — 20 records, abort if >20% fail ───────────────────────
    logger.info(f"Sanity-checking noticedesc API ({SANITY_CHECK_N} records)...")
    sanity_none = 0
    sanity_done = 0
    for stub in work_set[:SANITY_CHECK_N]:
        text, status = fetch_description(stub["notice_id"], api_key)
        sanity_done += 1
        quota_counter[0] += 1
        if text is None:
            sanity_none += 1
            logger.debug(f"  Sanity FAIL: {stub['notice_id']} → HTTP {status}")
            # 429 that survived a 30s retry means the daily quota is exhausted.
            # Every subsequent check will also 429 — fast-fail immediately rather
            # than spending 20 × 60s probing a wall.
            if status == 429:
                logger.error(
                    "429 confirmed after retry — daily API quota is exhausted. "
                    "Re-run after midnight Eastern Time. Aborting."
                )
                quota_file.write_text(json.dumps({"used": quota_counter[0], "date": run_date}))
                logger.removeHandler(file_handler)
                return
        else:
            label = "no desc" if text == "" else f"{len(text):,} chars"
            logger.info(f"  Sanity OK:   {stub['notice_id']} → HTTP {status} ({label})")

    fail_rate = sanity_none / sanity_done if sanity_done else 1.0
    if fail_rate > SANITY_FAIL_THRESHOLD:
        logger.error(
            f"Sanity check FAILED: {sanity_none}/{sanity_done} ({fail_rate:.0%}) returned errors. "
            f"Likely causes: daily quota active (try after midnight UTC), API key invalid, "
            f"or endpoint URL changed. Aborting."
        )
        quota_file.write_text(json.dumps({"used": quota_counter[0], "date": run_date}))
        logger.removeHandler(file_handler)
        return
    logger.info(f"Sanity check passed ({fail_rate:.0%} failure rate). Starting main run...")

    # Skip sanity records from main work set to avoid double-fetching
    work_set = work_set[SANITY_CHECK_N:]

    # ── Shared state for workers ────────────────────────────────────────────
    sb_url         = os.getenv("SUPABASE_URL")
    sb_key         = os.getenv("SUPABASE_SERVICE_KEY")
    shutdown_event = threading.Event()
    results_lock   = threading.Lock()
    quota_lock     = threading.Lock()

    counters = {"fetched": 0, "failed": 0, "no_description": 0,
                "see_attachment": 0, "cancelled": 0, "rate_limited": 0, "aborted": 0}
    # Mutable container so workers can increment without nonlocal
    quota_counter = [quota_used_today]

    # Per-failure log: notice_id + HTTP status for pattern analysis
    failure_log_path = log_dir / f"backfill_failures_{run_date}.tsv"
    failure_log = open(failure_log_path, "a", encoding="utf-8")
    failure_log.write("notice_id\thttp_status\ttimestamp\n")

    # see_attachment log: notice_ids for spot-checking threshold accuracy
    attachment_log_path = DATA_DIR / f"see_attachment_{run_date}.txt"
    attachment_log = open(attachment_log_path, "a", encoding="utf-8")

    def _fetch_and_update(stub):
        if shutdown_event.is_set():
            return "aborted"

        sb           = create_client(sb_url, sb_key)
        notice_id    = stub["notice_id"]
        original_url = stub.get("description", "")

        text, status = fetch_description(notice_id, api_key)
        time.sleep(DESC_WORKER_SLEEP)

        with quota_lock:
            quota_counter[0] += 1

        # 429 — rate limited even after the built-in retry in fetch_description
        if status == 429:
            with results_lock:
                counters["rate_limited"] += 1
                if counters["rate_limited"] >= RATE_LIMIT_ABORT_COUNT:
                    logger.error(f"{RATE_LIMIT_ABORT_COUNT} rate-limit hits — triggering shutdown to preserve quota")
                    shutdown_event.set()
            failure_log.write(f"{notice_id}\t{status}\t{datetime.now(timezone.utc).isoformat()}\n")
            return "rate_limited"

        # Real error (connection, 5xx that didn't resolve after retry)
        if text is None:
            failure_log.write(f"{notice_id}\t{status}\t{datetime.now(timezone.utc).isoformat()}\n")
            return "failed"

        # 404 — no description registered for this notice
        if text == "":
            return "no_description"

        lower = text.lower()

        # Withdrawn/cancelled notice — update status, don't write as description
        if any(phrase in lower for phrase in _WITHDRAWN_PHRASES):
            try:
                sb.table("opportunities").update({"status": "cancelled"}).eq("id", stub["id"]).execute()
            except Exception as e:
                logger.debug(f"Status update failed for {notice_id}: {e}")
            return "cancelled"

        # "See attachment" — substantive content is in a file, not this text
        if _is_see_attachment(text):
            attachment_log.write(f"{notice_id}\n")
            return "see_attachment"

        # Write description. Attempt to preserve original URL in description_url.
        update_data = {
            "description": text,
            "description_fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if original_url.startswith("http"):
            update_data["description_url"] = original_url

        try:
            sb.table("opportunities").update(update_data).eq("id", stub["id"]).execute()
            return "fetched"
        except Exception as e:
            # If description_url or description_fetched_at column doesn't exist yet,
            # retry with just the description field so the run doesn't fail.
            if "description_url" in str(e) or "description_fetched_at" in str(e):
                logger.warning("description_url/fetched_at column missing — run the ALTER TABLE DDL in Supabase")
                try:
                    sb.table("opportunities").update({"description": text}).eq("id", stub["id"]).execute()
                    return "fetched"
                except Exception as e2:
                    logger.warning(f"Fallback update failed for {notice_id}: {e2}")
                    failure_log.write(f"{notice_id}\tDB_ERROR\t{datetime.now(timezone.utc).isoformat()}\n")
                    return "failed"
            logger.warning(f"Update failed for {notice_id}: {e}")
            failure_log.write(f"{notice_id}\tDB_ERROR\t{datetime.now(timezone.utc).isoformat()}\n")
            return "failed"

    # ── Main run ────────────────────────────────────────────────────────────
    with ThreadPoolExecutor(max_workers=DESC_WORKERS) as pool:
        futures = [pool.submit(_fetch_and_update, stub) for stub in work_set]
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            with results_lock:
                counters[result] = counters.get(result, 0) + 1

            # Rolling failure-rate check — abort if >5% after first 100 completions
            if i >= 100 and i % 100 == 0:
                total_attempted = counters["fetched"] + counters["failed"] + counters["rate_limited"]
                hard_failures   = counters["failed"] + counters["rate_limited"]
                roll_rate       = hard_failures / total_attempted if total_attempted else 0
                if roll_rate > ABORT_FAIL_THRESHOLD:
                    logger.error(
                        f"Failure rate {roll_rate:.1%} exceeds {ABORT_FAIL_THRESHOLD:.0%} threshold "
                        f"after {i:,} records — aborting to preserve quota"
                    )
                    shutdown_event.set()

            if shutdown_event.is_set():
                logger.warning("Shutdown signal received — cancelling remaining futures")
                for f in futures:
                    f.cancel()
                break

            if i % 500 == 0 or i == len(work_set):
                total    = sum(counters.values())
                failures = counters["failed"] + counters["rate_limited"]
                logger.info(
                    f"Progress {i:,}/{len(work_set):,} | "
                    f"fetched={counters['fetched']:,} no_desc={counters['no_description']:,} "
                    f"see_attach={counters['see_attachment']:,} cancelled={counters['cancelled']:,} "
                    f"failed={failures:,} | "
                    f"fail_rate={failures/max(total,1):.1%} quota_used≈{quota_counter[0]:,}"
                )

    failure_log.close()
    attachment_log.close()

    # Persist quota count
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    quota_file.write_text(json.dumps({"used": quota_counter[0], "date": run_date}))

    elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
    logger.info(
        f"=== DESCRIPTION BACKFILL complete in {elapsed/60:.1f}min | "
        f"fetched={counters['fetched']:,} no_desc={counters['no_description']:,} "
        f"see_attach={counters['see_attachment']:,} cancelled={counters['cancelled']:,} "
        f"failed={counters['failed']:,} rate_limited={counters['rate_limited']:,} "
        f"aborted={counters['aborted']:,} quota_used≈{quota_counter[0]:,} ==="
    )
    logger.info(f"Failure log: {failure_log_path}")
    logger.info(f"See-attachment log: {attachment_log_path}")
    if capped or shutdown_event.is_set():
        remaining = len(all_stubs) - quota_available
        logger.info(f"Re-run tomorrow for remaining ~{max(remaining,0):,} records.")

    logger.removeHandler(file_handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM.gov bulk ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--full",  action="store_true", help="Full load: all opportunities from past 365 days")
    group.add_argument("--delta", action="store_true", help="Delta load: only records modified since last run")
    group.add_argument("--backfill-descriptions", action="store_true",
                       help="One-time: fetch real description text for all DB records that still have a SAM.gov URL")
    args = parser.parse_args()

    if args.full:
        run_full_load()
    elif args.delta:
        run_delta_load()
    elif args.backfill_descriptions:
        run_backfill_descriptions()
