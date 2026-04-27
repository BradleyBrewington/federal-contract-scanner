"""
Nightly Expiration Job
-----------------------
Marks opportunities whose response_deadline has passed as 'expired'.
Does NOT delete them — expired records are kept for re-compete tracking
and historical pattern analysis.

Run nightly after the delta load:
  python expiration.py
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


AGE_CUTOFF_DAYS = 365  # records with no deadline older than this are assumed closed


def run_expiration():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff_iso = (now - timedelta(days=AGE_CUTOFF_DAYS)).isoformat()
    logger.info(f"Running expiration check as of {now_iso} (age cutoff: {AGE_CUTOFF_DAYS} days)")

    # Pass 1: deadline is set and has passed
    result_deadline = (
        supabase.table("opportunities")
        .update({"status": "expired"})
        .eq("status", "active")
        .not_.is_("response_deadline", "null")
        .lt("response_deadline", now_iso)
        .execute()
    )
    count_deadline = len(result_deadline.data) if result_deadline.data else 0
    logger.info(f"Marked {count_deadline} opportunities expired (deadline passed)")

    # Pass 2: no deadline but posted more than AGE_CUTOFF_DAYS ago.
    # The vast majority of SAM.gov solicitations close within 180 days.
    # 365 days is a conservative cutoff — we'd rather keep a stale record
    # than prematurely expire a long-running IDIQ or open RFI.
    result_age = (
        supabase.table("opportunities")
        .update({"status": "expired"})
        .eq("status", "active")
        .is_("response_deadline", "null")
        .lt("posted_date", cutoff_iso)
        .execute()
    )
    count_age = len(result_age.data) if result_age.data else 0
    logger.info(f"Marked {count_age} opportunities expired (no deadline, posted > {AGE_CUTOFF_DAYS} days ago)")

    logger.info(f"Expiration complete: {count_deadline + count_age} total records marked expired")


if __name__ == "__main__":
    run_expiration()
