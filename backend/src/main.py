"""Main orchestrator — CLI with --scan and --scheduled modes."""

import argparse
import json
import os
import sys
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.scrapers.sam_gov import SamGovScraper
from src.scrapers.sbir_gov import SbirGovScraper
from src.scrapers.grants_gov import GrantsGovScraper
from src.scrapers.subnet_sba import scrape_subnet
from src.scoring.rule_engine import score_all, categorize_opportunity, _parse_dollar_amount
from src.scoring.ai_enrichment import enrich_all
from src.scoring.local_enrichment import enrich_with_local_llm
from src.parsers.attachment_parser import extract_attachment_texts
from src.notifications.email_sender import send_notification, send_weekly_digest, send_high_priority_alert
from src.export_excel import export_to_excel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
SUBNET_LAST_RUN_FILE = DATA_DIR / "subnet_last_run.txt"
SUBNET_INTERVAL_HOURS = 48


def load_config():
    with open(CONFIG_DIR / "settings.json") as f:
        settings = json.load(f)
    with open(CONFIG_DIR / "keywords.json") as f:
        keywords = json.load(f)
    return settings, keywords


def load_existing_opportunities():
    path = DATA_DIR / "opportunities.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_opportunities(opportunities):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "opportunities.json", "w") as f:
        json.dump(opportunities, f, indent=2, default=str)
    logger.info(f"Saved {len(opportunities)} opportunities")


def _should_run_subnet():
    """Returns True if SubNet hasn't been scraped in the last 48 hours."""
    if not SUBNET_LAST_RUN_FILE.exists():
        return True
    try:
        last_run_str = SUBNET_LAST_RUN_FILE.read_text().strip()
        last_run = datetime.fromisoformat(last_run_str)
        return datetime.utcnow() - last_run >= timedelta(hours=SUBNET_INTERVAL_HOURS)
    except Exception:
        return True


def _mark_subnet_ran():
    DATA_DIR.mkdir(exist_ok=True)
    SUBNET_LAST_RUN_FILE.write_text(datetime.utcnow().isoformat())


def _filter_min_value(opportunities, min_value):
    """Remove opportunities whose estimated value is known and below min_value."""
    if not min_value:
        return opportunities
    kept = []
    for opp in opportunities:
        val = _parse_dollar_amount(opp.get("estimated_value", ""))
        if val is not None and val < min_value:
            logger.debug(f"SKIP_VALUE: {opp.get('title', '')[:60]} — value ${val:,.0f} < min ${min_value:,.0f}")
            continue
        kept.append(opp)
    skipped = len(opportunities) - len(kept)
    if skipped:
        logger.info(f"SKIP_VALUE: filtered {skipped} opportunities below ${min_value:,.0f} minimum")
    return kept


_DEADLINE_FMTS = [
    ("%Y-%m-%dT%H:%M:%S", 19),
    ("%Y-%m-%d", 10),
    ("%m/%d/%Y", 10),
]


def _parse_deadline(dl_str):
    """Return datetime from deadline string, or None if unparseable."""
    if not dl_str:
        return None
    s = str(dl_str).strip()
    for fmt, length in _DEADLINE_FMTS:
        try:
            return datetime.strptime(s[:length], fmt)
        except ValueError:
            continue
    return None


def _pre_filter_opportunities(opportunities):
    """
    Hard-gate filter run BEFORE scoring. Eliminates records that should never
    enter the scoring or enrichment pipeline.

    Removes:
    - Award Notices, Justifications, J&As (contract already awarded)
    - Solicitations with response_deadline more than 2 days in the past
    - Sale of Surplus Property notices
    - Consolidation/Bundling notices

    Returns (kept, removed_count).
    """
    SKIP_TYPES = {
        "award notice",
        "justification",
        "justification and approval",
        "j&a",
        "sale of surplus property",
        "consolidate/(substantially) bundle",
    }
    kept = []
    removed = 0
    now = datetime.now()

    for opp in opportunities:
        opp_type = (opp.get("type") or "").strip().lower()

        # Type-based elimination
        if any(t in opp_type for t in SKIP_TYPES):
            removed += 1
            continue

        # Deadline-based elimination: if deadline is known and > 2 days past, drop it
        deadline_str = opp.get("response_deadline") or ""
        if deadline_str:
            dl = _parse_deadline(deadline_str)
            if dl is not None and (now - dl).days > 2:
                removed += 1
                continue

        kept.append(opp)

    logger.info(f"Pre-filter: removed {removed} ineligible/expired records, {len(kept)} remain")
    return kept, removed


def _secondary_dedup(opportunities):
    """
    Secondary dedup pass: catches same opportunity under different notice IDs
    (common with SAM.gov amendments). Uses normalized (title_prefix, agency) as key.
    Keeps the entry with the latest posted_date.
    """
    seen_title_agency = {}
    dupes = 0
    for opp in opportunities:
        title_key = (opp.get("title") or "")[:60].lower().strip()
        agency_key = (opp.get("agency") or "").lower().strip()
        key = (title_key, agency_key)

        if key in seen_title_agency:
            existing = seen_title_agency[key]
            existing_date = existing.get("posted_date", "") or ""
            new_date = opp.get("posted_date", "") or ""
            if new_date > existing_date:
                seen_title_agency[key] = opp
            dupes += 1
        else:
            seen_title_agency[key] = opp

    result = list(seen_title_agency.values())
    if dupes:
        logger.info(f"Secondary dedup: removed {dupes} duplicate records, {len(result)} remain")
    return result


def run_scan():
    """Execute a full scan cycle."""
    logger.info("=== Starting scan ===")
    settings, keywords_cfg = load_config()
    search_keywords = (
        keywords_cfg.get("positive_keywords_tier1", {}).get("terms", []) +
        keywords_cfg.get("positive_keywords_tier2", {}).get("terms", []) +
        keywords_cfg.get("positive_keywords_tier3", {}).get("terms", [])
    )
    naics_codes = settings.get("naics_codes", [])
    set_asides = settings.get("set_asides", [])

    all_opps = []
    seen_ids = set()

    def _add_opps(new_opps):
        """Deduplicate by id before adding."""
        for o in new_opps:
            if o["id"] not in seen_ids:
                seen_ids.add(o["id"])
                all_opps.append(o)

    # SAM.gov — NAICS-filtered pass
    if settings.get("sources", {}).get("sam_gov", True):
        logger.info("Scanning SAM.gov (NAICS filter)...")
        sam = SamGovScraper()
        _add_opps(sam.search(search_keywords, naics_codes, set_asides))

        # Keyword search pass for missing/wrong NAICS codes
        kw_list = settings.get("search_keywords", [])
        if kw_list:
            logger.info(f"Scanning SAM.gov (keyword pass — {len(kw_list)} terms)...")
            target_naics = set(naics_codes)
            kw_results = sam.search(kw_list, [], set_asides)
            kw_results = [o for o in kw_results if o.get("naics_code") in target_naics]
            _add_opps(kw_results)

    # SBIR.gov
    if settings.get("sources", {}).get("sbir_gov", True):
        logger.info("Scanning SBIR.gov...")
        sbir = SbirGovScraper()
        _add_opps(sbir.search(search_keywords, naics_codes, set_asides))

    # Grants.gov
    if settings.get("sources", {}).get("grants_gov", True):
        logger.info("Scanning Grants.gov...")
        grants = GrantsGovScraper()
        _add_opps(grants.search(search_keywords, naics_codes, set_asides))

    # SubNet SBA — runs every 48h, not every scan cycle
    if settings.get("sources", {}).get("subnet_sba", True):
        if _should_run_subnet():
            logger.info("Scanning SubNet SBA (48h cycle)...")
            try:
                subnet_opps = scrape_subnet()
                # Tag SubNet opps — categorize_opportunity() will override if engineering signals found
                for o in subnet_opps:
                    o["category"] = "general"
                _add_opps(subnet_opps)
                _mark_subnet_ran()
                logger.info(f"SubNet: added {len(subnet_opps)} opportunities")
            except Exception as e:
                logger.error(f"SubNet scrape failed: {e}", exc_info=True)
        else:
            logger.info("SubNet SBA: skipping (scraped within last 48h)")

    logger.info(f"Found {len(all_opps)} raw opportunities (deduplicated)")

    # Minimum contract value filter
    min_value = settings.get("contract_value_min", 0)
    if min_value:
        all_opps = _filter_min_value(all_opps, min_value)

    # Pre-filter: eliminate Award Notices, J&As, expired opps before scoring
    all_opps, pre_filtered = _pre_filter_opportunities(all_opps)
    logger.info(f"Pre-filter removed {pre_filtered} Award Notices / expired opps")

    # Merge with existing (preserve notes/status and carry over historical entries)
    existing = load_existing_opportunities()
    existing_map = {o["id"]: o for o in existing}
    today = datetime.now().strftime("%Y-%m-%d")
    new_ids = {o["id"] for o in all_opps}
    for opp in all_opps:
        if opp["id"] in existing_map:
            old = existing_map[opp["id"]]
            opp["notes"] = old.get("notes", "")
            opp["status"] = old.get("status", "new")
            opp["first_seen"] = old.get("first_seen", today)
            # Backward compat: existing opps with no notified field are treated as already notified
            # to prevent a flood of re-notifications on first run after this update
            opp["notified"] = old.get("notified", True)
            if old.get("enriched_with_attachment"):
                opp["enriched_with_attachment"] = True
            # Preserve AI enrichment if already done
            for key in ["ai_summary", "ai_requirements", "ai_feasibility", "ai_red_flags",
                        "ai_recommendation", "ai_go_no_go", "ai_confidence",
                        "ai_warnings_list", "ai_effort_hours", "ai_teaming_needed"]:
                if old.get(key):
                    opp[key] = old[key]
        else:
            opp["first_seen"] = today
            opp["notified"] = False

    # Secondary dedup: catch same opp under different notice IDs (SAM amendments)
    all_opps = _secondary_dedup(all_opps)

    # Score
    logger.info("Scoring opportunities...")
    score_all(all_opps)

    # Parse attachments for high scorers
    attachment_texts = {}
    if settings.get("attachment_download_enabled", True):
        for opp in all_opps:
            if opp["score"] >= 70 and opp.get("attachments"):
                logger.info(f"Parsing attachments for: {opp['title'][:60]}")
                text = extract_attachment_texts(opp["attachments"])
                if text:
                    attachment_texts[opp["id"]] = text

    # Re-enrichment: opp was previously enriched on description-only, but now has attachment text
    for opp in all_opps:
        needs_reenrich = (
            opp.get("ai_summary")
            and opp["id"] in attachment_texts
            and not opp.get("enriched_with_attachment")
        )
        if needs_reenrich:
            for key in ["ai_summary", "ai_requirements", "ai_feasibility", "ai_red_flags",
                        "ai_recommendation", "ai_go_no_go", "ai_confidence",
                        "ai_warnings_list", "ai_effort_hours", "ai_teaming_needed"]:
                opp.pop(key, None)
            opp["_pending_attachment_reenrich"] = True
            logger.info(f"Re-enrichment queued (new attachment): {opp.get('title', '')[:60]}")

    # Local enrichment (Ollama for brief summaries - all opportunities)
    if settings.get("local_enrichment_enabled", True):
        logger.info("Running local enrichment (Ollama)...")
        enrich_with_local_llm(all_opps)

    # AI enrichment (Claude Opus for high scorers only)
    if settings.get("ai_enrichment_enabled", True) and os.getenv("ANTHROPIC_API_KEY"):
        logger.info("Running Claude AI enrichment for MAYBE/REVIEW opportunities...")
        enrich_all(all_opps, score_threshold=50, attachment_texts=attachment_texts)

    # Finalize attachment re-enrichment flags
    for opp in all_opps:
        if opp.pop("_pending_attachment_reenrich", False):
            opp["enriched_with_attachment"] = True

    # High-priority alerts — fire immediately for score >= threshold, before digest
    high_alert_threshold = settings.get("high_value_alert_threshold", 75)
    if settings.get("email_notifications_enabled", True):
        for opp in all_opps:
            if (opp.get("score", 0) >= high_alert_threshold
                    and not opp.get("high_priority_notified", False)
                    and opp.get("status") != "SKIP"):
                send_high_priority_alert(opp)
                opp["high_priority_notified"] = True

    # Carry over historical opportunities not found in current scan
    carried_over = [o for o in existing if o["id"] not in new_ids]
    # Apply same pre-filter to carried-over opps (drop expired Award Notices, etc.)
    carried_over, co_filtered = _pre_filter_opportunities(carried_over)
    if co_filtered:
        logger.info(f"Pre-filter removed {co_filtered} ineligible/expired records from history")
    # Backfill category on carried-over opps that don't have one
    for o in carried_over:
        if not o.get("category"):
            o["category"] = categorize_opportunity(o, settings)
    all_opps.extend(carried_over)

    # Sort by score descending
    all_opps.sort(key=lambda x: x.get("score", 0), reverse=True)

    threshold = settings.get("score_threshold_notify", 70)

    # Log new opportunity count before emailing (Change 5)
    new_count = sum(
        1 for o in all_opps
        if not o.get("notified", False)
        and o.get("score", 0) >= threshold
        and o.get("status") != "SKIP"
    )
    logger.info(f"New opportunities above threshold: {new_count}")

    # Email — marks notified=True in-place; save AFTER so flags persist
    if settings.get("email_notifications_enabled", True):
        if new_count > 0:
            logger.info(f"Sending email notification (threshold: {threshold})...")
            send_notification(all_opps, score_threshold=threshold)

        # Weekly digest — send on configured day even if no new opportunities
        digest_day = settings.get("weekly_digest_day", "Sunday")
        if datetime.now().strftime("%A") == digest_day:
            logger.info(f"Today is {digest_day} — sending weekly digest...")
            send_weekly_digest(all_opps, score_threshold=threshold)

    # Save JSON — after email so notified flags are persisted
    save_opportunities(all_opps)

    # Export to single persistent Excel log
    excel_path = DATA_DIR / "opportunities.xlsx"
    export_to_excel(all_opps, excel_path)

    logger.info(f"=== Scan complete: {len(all_opps)} opportunities ===")
    return all_opps


def run_scheduled(interval_hours=6):
    """Run scans on a schedule."""
    logger.info(f"Starting scheduled mode — scanning every {interval_hours} hours")
    while True:
        try:
            run_scan()
        except Exception as e:
            logger.error(f"Scan failed: {e}", exc_info=True)
        logger.info(f"Next scan in {interval_hours} hours...")
        time.sleep(interval_hours * 3600)


def main():
    parser = argparse.ArgumentParser(description="Federal Contract Opportunity Scanner")
    parser.add_argument("--scan", action="store_true", help="Run a single scan")
    parser.add_argument("--scheduled", action="store_true", help="Run on schedule")
    parser.add_argument("--interval", type=int, default=6, help="Hours between scans (default: 6)")
    args = parser.parse_args()

    if args.scan:
        run_scan()
    elif args.scheduled:
        run_scheduled(args.interval)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
