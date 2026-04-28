"""
Nightly Maintenance Runner
--------------------------
Runs delta ingestion then expiration in sequence.
Designed to be called by Railway Cron at 02:00 UTC daily.

Railway Cron setup (do this once in the Railway dashboard):
  1. Open your Railway project
  2. Click "+ New" → "Cron Job"
  3. Connect the same GitHub repo (BradleyBrewington/Doom-Scroll-Gov-Contracts)
  4. Set start command:  python scripts/nightly.py
  5. Set schedule:       0 2 * * *   (2 AM UTC every day)
  6. Copy environment variables from your API service:
       SAM_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY

The cron service is separate from the Flask API service — it spins up, runs
the scripts, and exits. No dyno sleep issues.
"""

import subprocess
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT   = Path(__file__).resolve().parent.parent
INGEST = ROOT / "backend" / "src" / "ingestion" / "bulk_ingest.py"
EXPIRE = ROOT / "backend" / "src" / "ingestion" / "expiration.py"


def run(script: Path, *args) -> int:
    cmd = [sys.executable, str(script), *args]
    logger.info(f"Running: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        logger.error(f"{script.name} exited with code {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    logger.info("=== Nightly maintenance starting ===")

    rc_delta  = run(INGEST, "--delta")
    rc_expire = run(EXPIRE)

    logger.info(
        f"=== Nightly maintenance complete "
        f"(delta={rc_delta}, expiration={rc_expire}) ==="
    )

    # Non-zero exit so Railway marks the cron run as failed if either job fails
    sys.exit(max(rc_delta, rc_expire))
