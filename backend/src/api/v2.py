"""
Platform API v2
---------------
Serves the React frontend. Handles feed scoring and AI card summaries.

Auth model: React authenticates via Supabase Auth and passes the JWT in the
Authorization header. We decode it to get the user_id, then use the service
key to query Supabase (bypassing RLS is fine here — we enforce company_id
scoping manually).

Direct CRUD that doesn't need server logic (swipes, pipeline, profile edits)
goes React → Supabase directly, so this API stays small.
"""

import os
import re
import json
import random
import base64
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(env_path)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


def get_sb():
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def decode_jwt_payload(token: str) -> dict | None:
    """Decode Supabase JWT payload without signature verification.
    Security note: Supabase RLS + our manual company_id scoping handle
    authorization. The JWT just tells us who is calling.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.b64decode(payload_b64))
    except Exception:
        return None


def get_user_id() -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    payload = decode_jwt_payload(auth[7:])
    return payload.get("sub") if payload else None


def require_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_user_id():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_opportunity(opp: dict, profile: dict) -> int:
    """
    Score an opportunity against a company profile. Returns 0–100.
    Phase 1: pure rule-based weighted scoring. No ML yet.
    """
    score = 0

    naics_codes = {n["naics_code"] for n in profile.get("naics", [])}
    keywords = [k["keyword"].lower() for k in profile.get("keywords", []) if not k.get("is_exclusion")]
    exclusion_keywords = [k["keyword"].lower() for k in profile.get("keywords", []) if k.get("is_exclusion")]
    target_agencies = {a["agency_name"].lower() for a in profile.get("agencies", []) if a.get("relationship_type") in ("past_performance", "target")}
    excluded_agencies = {a["agency_name"].lower() for a in profile.get("agencies", []) if a.get("relationship_type") == "exclude"}
    contract_min = profile.get("contract_min") or 0
    contract_max = profile.get("contract_max") or float("inf")
    set_aside_eligibility = set(profile.get("set_aside_eligibility") or [])

    # Hard exclusions — return 0 immediately
    agency_lower = (opp.get("agency") or "").lower()
    if any(excl in agency_lower for excl in excluded_agencies):
        return 0

    desc_lower = (opp.get("description") or "").lower()
    title_lower = (opp.get("title") or "").lower()
    text = f"{title_lower} {desc_lower}"
    if any(kw in text for kw in exclusion_keywords):
        return 0

    # NAICS match — worth 35 points
    opp_naics = opp.get("naics_code") or ""
    if opp_naics in naics_codes:
        score += 35
    elif any(opp_naics.startswith(n[:4]) for n in naics_codes if len(n) >= 4):
        score += 15  # Related NAICS (same 4-digit group)

    # Set-aside alignment — worth 20 points
    opp_set_aside = (opp.get("set_aside_type") or "").upper()
    set_aside_map = {
        "SBA": "small_business",
        "8AN": "8a",
        "8A": "8a",
        "SDVOSBC": "sdvosb",
        "SDVOSBR": "sdvosb",
        "WOSB": "wosb",
        "EDWOSB": "wosb",
        "HZC": "hubzone",
        "HZS": "hubzone",
        "": "none",
        "NONE": "none",
    }
    normalized_set_aside = set_aside_map.get(opp_set_aside, "")
    if not opp_set_aside or normalized_set_aside == "none":
        score += 10  # Unrestricted — anyone can bid
    elif normalized_set_aside in set_aside_eligibility:
        score += 20  # Matches their eligibility

    # Contract value in range — worth 15 points
    opp_value = opp.get("value_max") or opp.get("value_min")
    if opp_value:
        if contract_min <= float(opp_value) <= contract_max:
            score += 15
        elif float(opp_value) < contract_min * 0.5 or float(opp_value) > contract_max * 2:
            score -= 10  # Way outside range

    # Agency affinity — worth 15 points
    if any(ta in agency_lower for ta in target_agencies):
        score += 15

    # Keyword overlap — worth up to 15 points
    if keywords:
        matches = sum(1 for kw in keywords if kw in text)
        keyword_score = min(15, int((matches / max(len(keywords), 1)) * 15 * 3))
        score += keyword_score

    # Deadline urgency adjustment
    deadline_str = opp.get("response_deadline")
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_left = (deadline - now).days
            if days_left < 0:
                return 0  # Expired
            elif days_left <= 7:
                score += 5   # Closing soon — boost visibility
            elif days_left <= 21:
                score += 2
        except ValueError:
            pass

    return max(0, min(100, score))


def build_company_profile(sb, company_id: str) -> dict:
    """Fetch company + related tables and return a unified profile dict."""
    company = sb.table("companies").select("*").eq("id", company_id).single().execute()
    naics = sb.table("company_naics").select("*").eq("company_id", company_id).execute()
    keywords = sb.table("company_keywords").select("*").eq("company_id", company_id).execute()
    agencies = sb.table("company_agencies").select("*").eq("company_id", company_id).execute()

    profile = company.data or {}
    profile["naics"] = naics.data or []
    profile["keywords"] = keywords.data or []
    profile["agencies"] = agencies.data or []
    return profile


# ---------------------------------------------------------------------------
# Feed endpoint
# ---------------------------------------------------------------------------

@app.route("/api/v2/feed", methods=["GET"])
@require_auth
def get_feed():
    """
    Returns a scored, ranked list of opportunity cards for the user's company.
    Excludes opportunities the user has already swiped.

    Query params:
      limit  — number of cards to return (default 20)
      offset — for pagination (default 0)
      mode   — 'algorithm' (default) or 'recent' (bypass scoring, show newest)
    """
    user_id = get_user_id()
    limit = min(int(request.args.get("limit", 20)), 50)
    mode = request.args.get("mode", "algorithm")

    sb = get_sb()

    # Get user's company
    user_row = sb.table("users").select("company_id").eq("id", user_id).single().execute()
    if not user_row.data:
        return jsonify({"error": "User not found. Complete onboarding first."}), 404
    company_id = user_row.data["company_id"]

    # Get already-swiped opportunity IDs for this user
    swiped = sb.table("swipes").select("opportunity_id").eq("user_id", user_id).execute()
    swiped_ids = [s["opportunity_id"] for s in (swiped.data or [])]

    # Fetch candidate opportunities from Supabase
    # Pre-filter: active status, not already swiped
    # Note: don't filter by deadline here — many valid records (awards, pre-sols,
    # sources sought) have null deadlines. Scoring handles expired ones (returns 0).
    now_iso = datetime.now(timezone.utc).isoformat()
    query = (
        sb.table("opportunities")
        .select("id,notice_id,title,agency,sub_agency,naics_code,set_aside_type,notice_type,value_min,value_max,pop_state,response_deadline,posted_date,ai_summary,description,status,source,attachments")
        .eq("status", "active")
        .order("posted_date", desc=True)
        .limit(500)  # Candidate pool for scoring
    )

    # Exclude swiped (Supabase supports not().in_() for reasonable list sizes)
    if swiped_ids:
        query = query.not_("id", "in", f"({','.join(swiped_ids)})")

    result = query.execute()
    candidates = result.data or []

    if not candidates:
        return jsonify({"cards": [], "total": 0, "exhausted": True})

    if mode == "recent":
        # Just return newest, no scoring
        cards = [format_card(o) for o in candidates[:limit]]
        return jsonify({"cards": cards, "total": len(candidates)})

    # Score all candidates against company profile
    profile = build_company_profile(sb, company_id)
    scored = [(score_opportunity(o, profile), o) for o in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Mix: 70% top scorers, 20% exploration, 10% urgency
    top_n = int(limit * 0.7)
    explore_n = int(limit * 0.2)
    urgent_n = limit - top_n - explore_n

    top_cards = [o for _, o in scored[:top_n]]

    # Exploration: take from mid-range scorers
    mid = scored[top_n: top_n + 50]
    random.shuffle(mid)
    explore_cards = [o for _, o in mid[:explore_n]]

    # Urgency: closing within 14 days, pick from remaining
    remaining = [o for _, o in scored[top_n:] if o not in explore_cards]
    urgent_cards = _pick_urgent(remaining, urgent_n)

    final = top_cards + explore_cards + urgent_cards
    random.shuffle(final[top_n:])  # Shuffle explore/urgent so they don't cluster at the end

    # Build score lookup for final set
    score_map = {id(o): s for s, o in scored}

    # Pre-generate AI summaries for the first 6 cards that don't have one yet.
    # This runs in parallel so latency is ~1 Haiku call (~0.5s) not 6 calls.
    needs_summary = [o for o in final[:6] if not o.get("ai_summary")]
    if needs_summary and ANTHROPIC_API_KEY:
        generated = _bulk_generate_summaries(needs_summary)
        for opp_id, summary_text in generated.items():
            # Patch the in-memory object and cache in DB
            for o in final:
                if o["id"] == opp_id:
                    o["ai_summary"] = summary_text
            sb.table("opportunities").update({"ai_summary": summary_text}).eq("id", opp_id).execute()

    cards = [format_card(o, score=score_map.get(id(o))) for o in final]

    return jsonify({"cards": cards, "total": len(candidates)})


def _generate_one_summary(opp: dict) -> tuple[str, str | None]:
    """Call Claude Haiku to generate a summary for one opportunity. Returns (opp_id, summary_text|None)."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw_desc = opp.get("description") or ""
        desc_text = raw_desc[:600] if not raw_desc.strip().startswith("http") else ""
        title = _clean_title(opp.get("title", ""))
        agency = opp.get("agency", "")
        naics = opp.get("naics_code", "")
        notice_type = opp.get("notice_type", "")
        set_aside = opp.get("set_aside_type", "") or ""
        value = opp.get("value_max")
        value_str = f"${float(value)/1e6:.1f}M" if value and float(value) >= 1e6 else (f"${float(value)/1e3:.0f}K" if value else "")

        prompt = f"""Summarize this federal contract opportunity in 2–3 sentences for a business development professional.
Focus on: what work is required, who the customer is, and any key constraints.
Be concrete and specific. Do not start with "This opportunity" or "The government".

Title: {title}
Agency: {agency}
Notice type: {notice_type}
NAICS: {naics}
{f'Set-aside: {set_aside}' if set_aside and set_aside.upper() not in ('NONE', '') else ''}
{f'Estimated value: {value_str}' if value_str else ''}
{f'Description: {desc_text}' if desc_text else 'No inline description — infer from title and agency context.'}

Write only the summary, no preamble."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return opp["id"], response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"Summary generation failed for {opp.get('id')}: {e}")
        return opp["id"], None


def _bulk_generate_summaries(opps: list) -> dict:
    """Generate summaries for multiple opportunities in parallel. Returns {opp_id: summary}."""
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(opps), 4)) as executor:
        futures = {executor.submit(_generate_one_summary, o): o["id"] for o in opps}
        for future in as_completed(futures, timeout=8):
            try:
                opp_id, summary = future.result()
                if summary:
                    results[opp_id] = summary
            except Exception as e:
                logger.warning(f"Summary future failed: {e}")
    return results


def _pick_urgent(opps: list, n: int) -> list:
    """Return up to n opportunities with deadlines within 14 days."""
    now = datetime.now(timezone.utc)
    urgent = []
    for o in opps:
        dl = o.get("response_deadline")
        if not dl:
            continue
        try:
            deadline = datetime.fromisoformat(dl.replace("Z", "+00:00"))
            if 0 < (deadline - now).days <= 14:
                urgent.append(o)
        except ValueError:
            continue
    return urgent[:n]


def _clean_title(title: str) -> str:
    """Clean SAM.gov titles for human readability."""
    text = (title or '').strip()
    if not text:
        return text
    # Strip PSC/FSC prefix patterns: "47--", "J--", "R699--", "17--GUIDE,"
    text = re.sub(r'^[A-Z0-9]{1,6}--\s*', '', text)
    # Add space after commas if missing
    text = re.sub(r',(?!\s)', ', ', text)
    # Title-case if mostly uppercase (>60% uppercase alpha chars)
    alpha = [c for c in text if c.isalpha()]
    if alpha and sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.6:
        # Custom title case that handles acronyms better
        words = text.split()
        stop = {'and', 'or', 'of', 'the', 'for', 'in', 'at', 'to', 'a', 'an',
                'with', 'on', 'by', 'from', 'its', 'as'}
        # Known 4-5 char acronyms common in federal contracting
        known_acronyms = {
            'HVAC', 'USAF', 'USMC', 'USMC', 'NASA', 'DISA', 'DCSA', 'ITAR',
            'DTRA', 'AUSA', 'SOCOM', 'NAICS', 'DARPA', 'CONUS', 'OCONUS',
        }
        result = []
        for i, w in enumerate(words):
            wl = w.lower()
            # Treat ≤3-char all-caps or known acronyms as acronyms to preserve
            is_acronym = (
                w.isupper() and w.isalpha() and wl not in stop and
                (len(w) <= 3 or w in known_acronyms)
            )
            if is_acronym:
                result.append(w)
            elif i == 0 or wl not in stop:
                result.append(w.capitalize())
            else:
                result.append(wl)
        text = ' '.join(result)
    return text.strip() or (title or '').strip()


def _safe_desc(text: str, max_len: int = 200) -> str:
    """Return text truncated to max_len, or '' if it's just a URL."""
    if not text:
        return ""
    text = text.strip()
    if text.startswith("http"):
        return ""
    return text[:max_len]


def format_card(opp: dict, score: int = None) -> dict:
    """Shape an opportunity into the minimal card payload the frontend needs."""
    # Deadline display
    deadline_str = opp.get("response_deadline")
    days_left = None
    urgency = "normal"
    if deadline_str:
        try:
            deadline = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
            days_left = (deadline - datetime.now(timezone.utc)).days
            if days_left <= 7:
                urgency = "red"
            elif days_left <= 21:
                urgency = "yellow"
            else:
                urgency = "green"
        except ValueError:
            pass

    # Value display
    value_display = None
    if opp.get("value_max"):
        v = float(opp["value_max"])
        if v >= 1_000_000_000:
            value_display = f"${v/1_000_000_000:.1f}B"
        elif v >= 1_000_000:
            value_display = f"${v/1_000_000:.1f}M"
        elif v >= 1_000:
            value_display = f"${v/1_000:.0f}K"
        else:
            value_display = f"${v:.0f}"

    return {
        "id": opp["id"],
        "notice_id": opp.get("notice_id"),
        "title": _clean_title(opp.get("title", "")),
        "agency": opp.get("agency", ""),
        "naics_code": opp.get("naics_code", ""),
        "set_aside_type": opp.get("set_aside_type", ""),
        "notice_type": opp.get("notice_type", ""),
        "value_display": value_display,
        "pop_state": opp.get("pop_state", ""),
        "days_left": days_left,
        "urgency": urgency,
        "response_deadline": deadline_str,
        "posted_date": opp.get("posted_date"),
        "ai_summary": opp.get("ai_summary"),  # May be None — frontend falls back to truncated description
        "description_preview": _safe_desc(opp.get("description"), 200),
        "has_attachments": bool(opp.get("attachments") and opp["attachments"] != "[]"),
        "score": score,
        "sam_url": f"https://sam.gov/opp/{opp.get('notice_id')}/view",
    }


# ---------------------------------------------------------------------------
# AI summary endpoint (on-demand, cached in DB)
# ---------------------------------------------------------------------------

@app.route("/api/v2/opportunities/<opp_id>/summary", methods=["POST"])
@require_auth
def generate_summary(opp_id: str):
    """
    Generate and cache an AI one-line summary for an opportunity card.
    Called when a card is rendered and ai_summary is null.
    """
    sb = get_sb()

    # Check if already generated (race condition safety)
    existing = sb.table("opportunities").select("ai_summary").eq("id", opp_id).single().execute()
    if existing.data and existing.data.get("ai_summary"):
        return jsonify({"summary": existing.data["ai_summary"]})

    opp = sb.table("opportunities").select("title,agency,description,naics_code,set_aside_type,value_max").eq("id", opp_id).single().execute()
    if not opp.data:
        return jsonify({"error": "Not found"}), 404

    _, summary_text = _generate_one_summary(opp.data)
    if not summary_text:
        return jsonify({"error": "Summary generation failed"}), 500

    # Cache in database
    sb.table("opportunities").update({"ai_summary": summary_text}).eq("id", opp_id).execute()
    return jsonify({"summary": summary_text})


# ---------------------------------------------------------------------------
# Opportunity detail
# ---------------------------------------------------------------------------

@app.route("/api/v2/opportunities/<opp_id>", methods=["GET"])
@require_auth
def get_opportunity(opp_id: str):
    """Full opportunity detail for the expanded card view."""
    sb = get_sb()
    result = sb.table("opportunities").select("*").eq("id", opp_id).single().execute()
    if not result.data:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result.data)


# ---------------------------------------------------------------------------
# Company profile (read — writes go direct to Supabase from frontend)
# ---------------------------------------------------------------------------

@app.route("/api/v2/company/profile", methods=["GET"])
@require_auth
def get_company_profile():
    user_id = get_user_id()
    sb = get_sb()
    user_row = sb.table("users").select("company_id").eq("id", user_id).single().execute()
    if not user_row.data:
        return jsonify({"error": "User not found"}), 404
    profile = build_company_profile(sb, user_row.data["company_id"])
    return jsonify(profile)


# ---------------------------------------------------------------------------
# Registration — create company + user records using service key (bypasses RLS)
# Called from the frontend after supabase.auth.signUp() succeeds
# ---------------------------------------------------------------------------

@app.route("/api/v2/auth/register", methods=["POST"])
def register():
    """
    Creates company and user records after Supabase Auth signup.
    Uses the service key so RLS doesn't block the inserts.
    Expects: { user_id, email, company_name }
    """
    data = request.get_json()
    user_id = data.get("user_id")
    email = data.get("email")
    company_name = data.get("company_name")

    if not all([user_id, email, company_name]):
        return jsonify({"error": "user_id, email, and company_name are required"}), 400

    sb = get_sb()

    # Check if user row already exists (idempotent)
    existing = sb.table("users").select("id,company_id").eq("id", user_id).execute()
    if existing.data:
        company = sb.table("companies").select("*").eq("id", existing.data[0]["company_id"]).single().execute()
        return jsonify({"company": company.data})

    try:
        # Create company
        company_result = sb.table("companies").insert({
            "name": company_name,
            "onboarding_complete": False,
            "onboarding_step": 1,
        }).execute()
        company_data = company_result.data[0]

        # Create user linked to company
        sb.table("users").insert({
            "id": user_id,
            "company_id": company_data["id"],
            "email": email,
            "role": "admin",
        }).execute()

        return jsonify({"company": company_data})
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/v2/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.0"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    logger.info(f"Starting Platform API v2 on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
