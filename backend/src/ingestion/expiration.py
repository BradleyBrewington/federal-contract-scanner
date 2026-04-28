"""
Nightly Expiration Job
-----------------------
Marks opportunities whose response_deadline has passed as 'expired'.
Does NOT delete them — expired records are kept for re-compete tracking
and historical pattern analysis.

Run nightly after the delta load:
  python expiration.py

Batches updates to avoid Supabase statement timeout on large result sets.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

AGE_CUTOFF_DAYS = 365   # records with no deadline older than this are assumed closed
UPDATE_BATCH    = 500   # IDs per UPDATE call — keeps each statement well under timeout


def _expire_batch(supabase, ids: list[str]) -> int:
    """Update a list of opportunity IDs to expired. Returns count written."""
    if not ids:
        return 0
    try:
        result = (
            supabase.table("opportunities")
            .update({"status": "expired"})
            .in_("id", ids)
            .execute()
        )
        return len(result.data) if result.data else len(ids)
    except Exception as e:
        logger.error(f"Batch update failed: {e}")
        return 0


def _collect_ids(supabase, filters: dict) -> list[str]:
    """
    Page through opportunities matching `filters` and return their IDs.
    Supabase SELECT is fast even on large tables; the slow part is the bulk UPDATE.
    """
    ids = []
    offset = 0
    page = 1000
    while True:
        q = supabase.table("opportunities").select("id").eq("status", "active")
        for method, *args in filters:
            q = getattr(q, method)(*args)
        batch = q.range(offset, offset + page - 1).execute()
        rows = batch.data or []
        ids.extend(r["id"] for r in rows)
        if len(rows) < page:
            break
        offset += page
    return ids


def run_expiration():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    now = datetime.now(timezone.utc)
    now_iso    = now.isoformat()
    cutoff_iso = (now - timedelta(days=AGE_CUTOFF_DAYS)).isoformat()
    logger.info(f"Running expiration check as of {now_iso} (age cutoff: {AGE_CUTOFF_DAYS} days)")

    total = 0

    # ── Pass 1: deadline is set and has passed ──────────────────────────────
    logger.info("Pass 1: collecting records with passed deadline...")
    ids_deadline = _collect_ids(supabase, [
        ("not_.is_", "response_deadline", "null"),
        ("lt",        "response_deadline", now_iso),
    ])
    logger.info(f"Pass 1: {len(ids_deadline):,} records to expire")

    for i in range(0, len(ids_deadline), UPDATE_BATCH):
        chunk = ids_deadline[i : i + UPDATE_BATCH]
        written = _expire_batch(supabase, chunk)
        total += written
        logger.info(f"Pass 1: expired {min(i + UPDATE_BATCH, len(ids_deadline)):,} / {len(ids_deadline):,}")

    # ── Pass 2: no deadline, posted more than AGE_CUTOFF_DAYS ago ──────────
    logger.info("Pass 2: collecting records with no deadline older than cutoff...")
    ids_age = _collect_ids(supabase, [
        ("is_",  "response_deadline", "null"),
        ("lt",   "posted_date",       cutoff_iso),
    ])
    logger.info(f"Pass 2: {len(ids_age):,} records to expire")

    for i in range(0, len(ids_age), UPDATE_BATCH):
        chunk = ids_age[i : i + UPDATE_BATCH]
        written = _expire_batch(supabase, chunk)
        total += written
        logger.info(f"Pass 2: expired {min(i + UPDATE_BATCH, len(ids_age)):,} / {len(ids_age):,}")

    logger.info(f"Expiration complete: {total:,} total records marked expired")


if __name__ == "__main__":
    run_expiration()
