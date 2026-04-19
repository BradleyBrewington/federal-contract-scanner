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
from datetime import datetime, timezone
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


def run_expiration():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    supabase = create_client(url, key)

    now = datetime.now(timezone.utc).isoformat()
    logger.info(f"Running expiration check as of {now}")

    result = (
        supabase.table("opportunities")
        .update({"status": "expired"})
        .eq("status", "active")
        .lt("response_deadline", now)
        .execute()
    )

    count = len(result.data) if result.data else 0
    logger.info(f"Marked {count} opportunities as expired")


if __name__ == "__main__":
    run_expiration()
