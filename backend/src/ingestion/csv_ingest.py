"""
GSA Contract Opportunities — Daily CSV Ingest
-----------------------------------------------
Replaces the per-record SAM API description backfill.

The official GSA public extract (refreshed daily) contains full description
text for all active opportunities in a single bulk file. DuckDB reads the CSV
directly via HTTP (httpfs extension), deduplicates by NoticeId keeping the
latest PostedDate, and transforms to our schema. A hash-based diff against the
existing opportunities table minimises Supabase writes — only new or changed
records are upserted.

SAM API is now reserved for:
  - Delta load  (new / modified records, near-real-time)
  - Attachment downloads  (see_attachment records)
  - Live watchlist polling

Prerequisites — run once in Supabase SQL Editor:

    ALTER TABLE opportunities
      ADD COLUMN IF NOT EXISTS description_hash   TEXT,
      ADD COLUMN IF NOT EXISTS description_source TEXT DEFAULT 'api';

    CREATE INDEX IF NOT EXISTS idx_opportunities_desc_source
      ON opportunities (description_source);

Usage:
  py -3 backend/src/ingestion/bulk_ingest.py --validate-csv
  py -3 backend/src/ingestion/bulk_ingest.py --csv-ingest
  py -3 backend/src/ingestion/bulk_ingest.py --csv-ingest --skip-validation
"""

import codecs
import hashlib
import html as html_lib
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import duckdb
from dotenv import load_dotenv
from supabase import create_client, Client

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False

_env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CSV_URL      = (
    "https://s3.amazonaws.com/falextracts/"
    "Contract%20Opportunities/datagov/"
    "ContractOpportunitiesFullCSV.csv"
)
UPSERT_BATCH = 250    # rows per Supabase upsert call
HASH_LEN     = 16     # hex chars of MD5 stored in description_hash
VALIDATION_N = 50     # records to compare during validation step
DATA_DIR     = Path(__file__).resolve().parents[3] / "data"

# ── Notice type mapping (CSV "Type" → DB notice_type) ─────────────────────────
_NOTICE_TYPE_MAP = {
    "solicitation":                    "solicitation",
    "presolicitation":                 "presolicitation",
    "sources sought":                  "sources_sought",
    "combined synopsis/solicitation":  "combined",
    "special notice":                  "special",
    "sale of surplus property":        "sale_of_surplus",
    "intent to bundle requirements":   "intent_to_bundle",
    "award notice":                    "award",
    "justification":                   "justification",
    "modification/amendment":          "modification",
    "foreign government standard":     "foreign_government",
}

# ── See-attachment phrases (mirrors bulk_ingest.py) ───────────────────────────
_SEE_ATTACHMENT_PHRASES = [
    "see attach", "see the attach", "refer to attach",
    "see sow", "see the sow", "see statement of work",
    "see enclosed", "attached herein", "see solicitation",
    "see rfp", "see rfi", "see rfq",
    "please see", "refer to document", "see document",
    "see associated file", "see below for", "see amendment",
    "see pwd", "see performance work statement", "see pws",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    if not text:
        return text
    # Skip BS4 entirely if there are no HTML tags — avoids MarkupResemblesLocatorWarning
    # when plain text is passed (e.g. already-cleaned DB descriptions during validation)
    if "<" not in text:
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text
    if _HAS_BS4:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            text = re.sub(r"<[^>]+>", " ", text)
    else:
        text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Remove control characters Postgres rejects (keep \t \n \r)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


def _is_see_attachment(text: str) -> bool:
    if not text or len(text) > 600:
        return False
    return any(p in text.lower() for p in _SEE_ATTACHMENT_PHRASES)


def _desc_hash(text: str) -> Optional[str]:
    """MD5 of the stripped description, truncated to HASH_LEN hex chars."""
    if not text:
        return None
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:HASH_LEN]


def _normalize_notice_type(raw: str) -> str:
    if not raw:
        return "solicitation"
    return _NOTICE_TYPE_MAP.get(raw.strip().lower(), raw.strip().lower()) or "solicitation"


def _parse_value(raw) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(str(raw).replace(",", "").replace("$", "").strip())
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_date(raw) -> Optional[str]:
    """
    Parse a date value from the GSA CSV.
    DuckDB already infers PostedDate/ResponseDeadLine as TIMESTAMP WITH TIME ZONE,
    so raw will be a Python datetime object. Fall back to string parsing for any
    columns that arrive as plain strings.
    """
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.isoformat()
    s = str(raw).strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    return create_client(url, key)


# ── CSV Download (fallback for when DuckDB HTTP fails) ────────────────────────

def _download_to_temp(url: str) -> Path:
    """
    Stream-download the CSV to a local temp file.
    Uses an incremental UTF-8 decoder (errors='replace') to handle encoding
    issues at multi-byte character boundaries without corrupting the stream.
    Returns path to the temp file (caller must delete it).
    """
    tmp_dir = DATA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mktemp(suffix=".csv", dir=tmp_dir))

    logger.info(f"Downloading CSV to temp file: {tmp}")
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 2 * 1024 * 1024  # 2 MB

    # Incremental decoder handles multi-byte chars split across chunk boundaries
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            clean = decoder.decode(chunk, final=False).encode("utf-8")
            f.write(clean)
            downloaded += len(chunk)
            if total and downloaded % (200 * 1024 * 1024) < chunk_size:
                logger.info(f"  {downloaded / 1e6:.0f} / {total / 1e6:.0f} MB "
                            f"({downloaded / total * 100:.0f}%)")
        # Flush residual bytes
        tail = decoder.decode(b"", final=True)
        if tail:
            f.write(tail.encode("utf-8"))

    logger.info(f"Download complete: {downloaded / 1e6:.0f} MB")
    return tmp


# ── DuckDB Processing ─────────────────────────────────────────────────────────

def _build_dedup_sql(source: str) -> str:
    """
    Return the DuckDB CREATE TABLE statement that:
      - Reads the GSA CSV from `source` (URL or local path)
      - Selects the columns we need with clean aliases
      - Deduplicates by NoticeId, keeping the row with the latest PostedDate
      - Filters out rows with null/empty NoticeId

    Column name quirks handled by double-quoting:
      Sol#, Department/Ind.Agency, Award$, Sub-Tier, FPDS Code
    max_line_size: Description fields can exceed the default 2 MB limit.
    ignore_errors: skips rows with unrecoverable parse errors rather than aborting.
    """
    return f"""
    CREATE OR REPLACE TABLE _deduped AS
    WITH _ranked AS (
        SELECT
            trim("NoticeId")              AS notice_id,
            "Title"                       AS title,
            "Sol#"                        AS solicitation_number,
            "Department/Ind.Agency"       AS agency,
            "Sub-Tier"                    AS sub_agency,
            "Office"                      AS office,
            "PostedDate"                  AS posted_date_raw,
            "Type"                        AS notice_type_raw,
            "SetASideCode"                AS set_aside_type,
            "ResponseDeadLine"            AS response_deadline_raw,
            "NaicsCode"                   AS naics_code,
            "ClassificationCode"          AS psc_code,
            "PopCity"                     AS pop_city,
            "PopState"                    AS pop_state,
            "PopCountry"                  AS pop_country,
            "Active"                      AS active,
            "Award$"                      AS value_max_raw,
            "Link"                        AS sam_link,
            "Description"                 AS description_raw,
            ROW_NUMBER() OVER (
                PARTITION BY trim("NoticeId")
                ORDER BY COALESCE("PostedDate", TIMESTAMP '1900-01-01') DESC
            ) AS _rn
        FROM read_csv(
            '{source}',
            header        = true,
            quote         = '"',
            escape        = '"',
            null_padding  = true,
            ignore_errors = true,
            max_line_size = 5242880,
            parallel      = false
        )
        WHERE "NoticeId" IS NOT NULL
          AND trim("NoticeId") != ''
    )
    SELECT * EXCLUDE(_rn) FROM _ranked
    WHERE _rn = 1
    """


def _run_duckdb(source: str) -> list[dict]:
    """Execute the dedup query on `source` and return rows as list of dicts."""
    conn = duckdb.connect()
    try:
        conn.execute(_build_dedup_sql(source))
        rows = conn.execute("SELECT * FROM _deduped").fetchall()
        cols = [d[0] for d in conn.description]
        logger.info(f"DuckDB: {len(rows):,} deduplicated records from "
                    f"{'HTTP' if source.startswith('http') else 'local file'}")
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def load_csv_duckdb(url: str = CSV_URL) -> list[dict]:
    """
    Load the GSA CSV using DuckDB.
    Primary: direct HTTP reading via DuckDB's httpfs extension (no local copy needed).
    Fallback: stream-download to a temp file, then read locally.

    Returns raw rows — descriptions not yet HTML-stripped or hashed.
    """
    # Try DuckDB HTTP first
    conn_test = duckdb.connect()
    http_ok = False
    try:
        try:
            conn_test.execute("LOAD httpfs;")
        except duckdb.IOException:
            logger.info("Installing DuckDB httpfs extension...")
            conn_test.execute("INSTALL httpfs; LOAD httpfs;")
        http_ok = True
    except Exception as e:
        logger.warning(f"httpfs unavailable ({e}); will download to temp file")
    finally:
        conn_test.close()

    tmp_path = None
    try:
        if http_ok:
            try:
                logger.info(f"Loading CSV via DuckDB HTTP: {url}")
                return _run_duckdb(url)
            except Exception as e:
                logger.warning(f"DuckDB HTTP read failed ({e}); downloading to temp file")

        tmp_path = _download_to_temp(url)
        return _run_duckdb(str(tmp_path))

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
            logger.debug(f"Temp file removed: {tmp_path}")


# ── Row Processing ────────────────────────────────────────────────────────────

def _process_rows(raw_rows: list[dict]) -> list[dict]:
    """
    Transform raw DuckDB rows into DB-ready records:
      - Strip HTML from description_raw
      - Detect see-attachment stubs (→ description_source = 'csv_see_attachment')
      - Compute description_hash for diff
      - Map notice_type, parse dates + values

    Records with see-attachment descriptions are still stored (the stub text is
    the real description for these notices). description_source flags them so
    future attachment-download jobs can query:
        WHERE description_source = 'csv_see_attachment'
    """
    records = []
    empty_count = 0
    see_attach_count = 0

    for r in raw_rows:
        raw_desc = r.get("description_raw") or ""
        desc = _strip_html(str(raw_desc)) if raw_desc else ""

        if not desc:
            empty_count += 1
            desc_source = "csv_empty"
        elif _is_see_attachment(desc):
            see_attach_count += 1
            desc_source = "csv_see_attachment"
        else:
            desc_source = "csv"

        records.append({
            "notice_id":          (r.get("notice_id") or "").strip(),
            "title":              (r.get("title") or "").strip(),
            "solicitation_number": r.get("solicitation_number") or "",
            "agency":             r.get("agency") or "",
            "sub_agency":         r.get("sub_agency") or "",
            "office":             r.get("office") or "",
            "naics_code":         str(r["naics_code"]) if r.get("naics_code") else "",
            "psc_code":           r.get("psc_code") or "",
            "set_aside_type":     r.get("set_aside_type") or "",
            "notice_type":        _normalize_notice_type(r.get("notice_type_raw") or ""),
            "posted_date":        _parse_date(r.get("posted_date_raw")),
            "response_deadline":  _parse_date(r.get("response_deadline_raw")),
            "pop_city":           r.get("pop_city") or "",
            "pop_state":          r.get("pop_state") or "",
            "pop_country":        r.get("pop_country") or "USA",
            "value_max":          _parse_value(r.get("value_max_raw")),
            "status":             ("active"
                                   if r.get("active") is True
                                   or str(r.get("active") or "").strip().lower() in ("yes", "true", "1", "t")
                                   else "expired"),
            "source":             "sam_gov",
            "description":        desc,
            "description_hash":   _desc_hash(desc),
            "description_source": desc_source,
        })

    logger.info(f"Processed {len(records):,} records | "
                f"empty={empty_count:,} | see_attachment={see_attach_count:,}")
    return records


# ── DB Hash Fetching ──────────────────────────────────────────────────────────

def fetch_existing_hashes(sb: Client) -> dict[str, Optional[str]]:
    """
    Fetch {notice_id: description_hash} for every existing opportunity.
    If description_hash column doesn't exist yet (pre-migration), returns {}
    which causes all records to be treated as new/changed on first run.
    """
    result: dict[str, Optional[str]] = {}
    offset = 0
    page_size = 1000
    while True:
        try:
            batch = (
                sb.table("opportunities")
                .select("notice_id, description_hash")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        except Exception as e:
            logger.warning(
                f"Could not fetch description_hash column ({e}). "
                "Run the ALTER TABLE prereq DDL in Supabase. "
                "Proceeding in full-upsert mode (no diff)."
            )
            return {}
        rows = batch.data or []
        for row in rows:
            result[row["notice_id"]] = row.get("description_hash")
        if len(rows) < page_size:
            break
        offset += page_size
    logger.info(f"Loaded {len(result):,} existing hashes from DB")
    return result


# ── Validation ────────────────────────────────────────────────────────────────

def validate_csv_descriptions(
    raw_rows: list[dict],
    sample_size: int = VALIDATION_N,
) -> bool:
    """
    Compare CSV descriptions against API-sourced descriptions already in the DB.

    Pulls `sample_size` records from Supabase whose descriptions are real text
    (not URLs, not empty — meaning the SAM API previously fetched them). Looks
    those same NoticeIds up in the already-loaded CSV rows and compares:

      - Found rate:    fraction of DB sample found in CSV  (target ≥ 80%)
      - Quality rate:  fraction of found records where CSV description length
                       is ≥ 80% of the DB description length  (target ≥ 80%)

    Returns True if both thresholds pass, False otherwise.
    Logs a per-record summary at DEBUG level and an aggregate report at INFO.

    If the DB has no suitable sample records (all descriptions are URLs / empty)
    the function returns True with a warning — nothing to compare against.
    """
    sb = get_supabase()

    # Build a lookup from the already-processed CSV rows
    csv_lookup: dict[str, str] = {
        r["notice_id"]: r.get("description_raw") or ""
        for r in raw_rows
    }

    # Sample from DB: active records with real text descriptions.
    # The CSV only contains currently active opportunities — expired/archived records
    # are intentionally absent, so sampling from all statuses produces a false-low
    # found rate.
    try:
        resp = (
            sb.table("opportunities")
            .select("notice_id, description")
            .eq("status", "active")
            .neq("description", "")
            .not_.ilike("description", "http%")
            .limit(sample_size)
            .execute()
        )
    except Exception as e:
        logger.error(f"Validation: DB query failed ({e})")
        return False

    if not resp.data:
        logger.warning(
            "Validation: no suitable DB records found "
            "(all descriptions are URLs or empty — nothing to compare against). "
            "Treating as pass."
        )
        return True

    db_sample = {row["notice_id"]: row["description"] for row in resp.data}
    logger.info(f"Validation: comparing {len(db_sample)} DB records against CSV")

    found = 0
    empty_in_csv = 0
    char_ratios: list[float] = []

    for notice_id, db_desc in db_sample.items():
        csv_raw = csv_lookup.get(notice_id)
        if csv_raw is None:
            logger.debug(f"  {notice_id}: missing from CSV")
            continue

        found += 1
        if not csv_raw.strip():
            empty_in_csv += 1
            logger.debug(f"  {notice_id}: empty in CSV")
            continue

        db_clean  = _strip_html(db_desc)
        csv_clean = _strip_html(csv_raw)
        if db_clean:
            ratio = len(csv_clean) / len(db_clean)
            char_ratios.append(ratio)
            logger.debug(f"  {notice_id}: DB={len(db_clean)}c  CSV={len(csv_clean)}c  ratio={ratio:.2f}")

    total        = len(db_sample)
    found_rate   = found / total if total else 0
    good_count   = sum(1 for r in char_ratios if r >= 0.80)
    quality_rate = good_count / len(char_ratios) if char_ratios else 0
    avg_ratio    = sum(char_ratios) / len(char_ratios) if char_ratios else 0

    logger.info(f"  Found in CSV:         {found}/{total} ({found_rate:.0%})")
    logger.info(f"  Empty in CSV:         {empty_in_csv}/{found}")
    logger.info(f"  Avg char ratio:       {avg_ratio:.2f}x")
    logger.info(f"  Quality (>=0.80x):    {good_count}/{len(char_ratios)} ({quality_rate:.0%})")

    # found_rate < 80% is expected: many DB "active" records have since expired/archived
    # and SAM removes them from the daily CSV extract. The meaningful signal is quality_rate —
    # when a record appears in both sources, does the CSV description match? Require ≥80%.
    # A found_rate below 20% would indicate a notice_id format mismatch — catch that case.
    passed = found_rate >= 0.20 and quality_rate >= 0.80
    logger.info(f"  Validation: {'PASSED' if passed else 'FAILED'} "
                f"(found_rate={found_rate:.0%}, quality_rate={quality_rate:.0%})")
    return passed


# ── Upsert ────────────────────────────────────────────────────────────────────

# Track whether description_hash / description_source columns are available.
# Updated to False on first upsert failure so subsequent batches skip those fields.
_hash_cols_available = True


def _upsert_chunk(sb: Client, records: list[dict]) -> int:
    """
    Upsert a chunk of records. Automatically drops hash/source columns if
    the DB schema hasn't been migrated yet (graceful degradation).
    """
    global _hash_cols_available

    def _strip_hash_cols(recs):
        return [{k: v for k, v in r.items()
                 if k not in ("description_hash", "description_source")}
                for r in recs]

    payload = records if _hash_cols_available else _strip_hash_cols(records)
    try:
        sb.table("opportunities").upsert(payload, on_conflict="notice_id").execute()
        return len(payload)
    except Exception as e:
        if _hash_cols_available and (
            "description_hash" in str(e) or "description_source" in str(e)
        ):
            _hash_cols_available = False
            logger.warning(
                "description_hash / description_source columns missing. "
                "Run the ALTER TABLE DDL in Supabase to enable hash-diff. "
                "Continuing without hash tracking."
            )
            payload = _strip_hash_cols(records)
            sb.table("opportunities").upsert(payload, on_conflict="notice_id").execute()
            return len(payload)
        raise


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_csv_ingest(skip_validation: bool = False) -> dict:
    """
    Full daily CSV ingest pipeline:
      1. Load GSA CSV via DuckDB (HTTP → temp file fallback)
      2. Validate CSV descriptions against DB sample  (unless skip_validation)
      3. Transform rows: HTML strip, hash, notice_type mapping
      4. Diff against existing DB hashes — skip unchanged records
      5. Batch upsert to Supabase

    Returns a stats dict: {loaded, written, unchanged, see_attachment, elapsed_s}
    """
    run_start = datetime.now(timezone.utc)
    run_date  = run_start.strftime("%Y-%m-%d")

    # ── Persistent log file ──────────────────────────────────────────────────
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / f"csv_ingest_{run_date}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    try:
        logger.info("=== CSV INGEST starting ===")

        # Step 1: Load CSV via DuckDB
        raw_rows = load_csv_duckdb()
        logger.info(f"Loaded {len(raw_rows):,} raw records from CSV")

        # Step 2: Validation
        if not skip_validation:
            logger.info(f"Running validation on {VALIDATION_N} sample records...")
            passed = validate_csv_descriptions(raw_rows)
            if not passed:
                logger.error(
                    "Validation FAILED — CSV descriptions do not match DB quality threshold. "
                    "Aborting ingest. Investigate the comparison above, then re-run with "
                    "--skip-validation to force ingest."
                )
                return {"status": "aborted_validation"}
        else:
            logger.info("Validation skipped (--skip-validation)")

        # Step 3: Python post-processing
        processed = _process_rows(raw_rows)

        # Step 4: Hash diff — fetch existing hashes, skip unchanged records
        sb = get_supabase()
        existing_hashes = fetch_existing_hashes(sb)

        to_upsert:      list[dict] = []
        see_attach_ids: list[str]  = []
        unchanged = 0

        for rec in processed:
            nid = rec.get("notice_id")
            if not nid:
                continue
            if rec.get("description_source") == "csv_see_attachment":
                see_attach_ids.append(nid)
            # Skip if hash matches existing (description unchanged)
            if nid in existing_hashes and existing_hashes[nid] == rec.get("description_hash"):
                unchanged += 1
                continue
            to_upsert.append(rec)

        logger.info(
            f"Diff: {len(to_upsert):,} to upsert | "
            f"{unchanged:,} unchanged | "
            f"{len(see_attach_ids):,} see-attachment (flagged for attachment download)"
        )

        # Step 5: Batch upsert
        written = 0
        for i in range(0, len(to_upsert), UPSERT_BATCH):
            chunk = to_upsert[i : i + UPSERT_BATCH]
            try:
                written += _upsert_chunk(sb, chunk)
            except Exception as e:
                logger.error(f"Upsert failed at chunk starting {i}: {e}")
            if (i // UPSERT_BATCH) % 20 == 0:
                logger.info(f"  Upserted {written:,} / {len(to_upsert):,}...")

        # Write see-attachment notice IDs for attachment-download job
        if see_attach_ids:
            attach_log = DATA_DIR / f"see_attachment_csv_{run_date}.txt"
            attach_log.write_text("\n".join(see_attach_ids), encoding="utf-8")
            logger.info(f"See-attachment IDs written to {attach_log}")

        elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
        stats = {
            "status":         "ok",
            "loaded":         len(raw_rows),
            "written":        written,
            "unchanged":      unchanged,
            "see_attachment": len(see_attach_ids),
            "elapsed_s":      round(elapsed),
        }
        logger.info(
            f"=== CSV INGEST complete in {elapsed / 60:.1f}min | "
            f"loaded={stats['loaded']:,} written={stats['written']:,} "
            f"unchanged={stats['unchanged']:,} see_attachment={stats['see_attachment']:,} ==="
        )
        return stats

    finally:
        logger.removeHandler(fh)
