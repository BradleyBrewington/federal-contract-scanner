"""Scoring engine — 4-category rubric + hard disqualifiers."""

import json
import os
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")

# Statuses set by a human — the scorer must not overwrite these
USER_STATUSES = {"reviewing", "bid", "no-bid", "won", "lost"}


def _load_json(filename):
    path = os.path.join(CONFIG_DIR, filename)
    with open(path, "r") as f:
        return json.load(f)


def _match(term, text):
    """Case-insensitive whole-word match (non-word boundary lookaround)."""
    pattern = r'(?<!\w)' + re.escape(term) + r'(?!\w)'
    return bool(re.search(pattern, text, re.IGNORECASE))


def _find_matches(terms, text):
    """Return terms from `terms` that appear as whole words in `text`."""
    return [t for t in terms if _match(t, text)]


def _parse_dollar_amount(s):
    """Parse '$250,000', '250K', '1.5M', etc. → float or None."""
    if not s:
        return None
    s = str(s).replace(",", "").replace("$", "").strip()
    try:
        if s.upper().endswith("B"):
            return float(s[:-1]) * 1_000_000_000
        elif s.upper().endswith("M"):
            return float(s[:-1]) * 1_000_000
        elif s.upper().endswith("K"):
            return float(s[:-1]) * 1_000
        return float(s)
    except (ValueError, TypeError):
        return None


def _extract_contract_value(opp):
    """
    Return (value_float_or_None, is_idiq_bool).
    Uses estimated_value field first, then scans title + description.
    For IDIQ the ceiling covers the full ordering period — individual TOs are smaller.
    """
    ev = opp.get("estimated_value", "")
    if ev:
        val = _parse_dollar_amount(ev)
        if val is not None:
            return val, False

    title = (opp.get("title") or "").lower()
    desc = (opp.get("description") or "").lower()
    text = title + " " + desc

    is_idiq = bool(re.search(
        r'\bidiq\b|\bindefinite[- ]delivery\b|\bindefinite[- ]quantity\b',
        text, re.IGNORECASE
    ))

    # Range: "$X to $Y" or "$X – $Y"
    range_pat = r'\$\s*([\d,\.]+)\s*([kmKM]?)\s*(?:to|[-\u2013])\s*\$\s*([\d,\.]+)\s*([kmKM]?)'
    rm = re.search(range_pat, text)
    if rm:
        lo = _parse_dollar_amount(rm.group(1).replace(",", "") + rm.group(2))
        hi = _parse_dollar_amount(rm.group(3).replace(",", "") + rm.group(4))
        if lo and hi:
            return (lo + hi) / 2.0, is_idiq

    # Single amounts — collect all, use minimum as conservative estimate
    amounts = []
    for m in re.finditer(r'\$\s*([\d,]+(?:\.\d+)?)\s*([kmKMbB]?)', text):
        val = _parse_dollar_amount(m.group(1).replace(",", "") + m.group(2))
        if val and val >= 1000:
            amounts.append(val)
    if amounts:
        return min(amounts), is_idiq

    return None, is_idiq


# ─────────────────────────────────────────────────────────────────────────────
# Hard Disqualifiers
# ─────────────────────────────────────────────────────────────────────────────

def check_hard_disqualifiers(text, opp, settings):
    """Return list of triggered disqualifier strings, or empty list if none."""
    triggered = []

    # Award notice — already awarded, nothing to bid
    opp_type = (opp.get("type") or "").strip().lower()
    if any(t in opp_type for t in ("award notice", "intent to award", "j&a", "justification")):
        triggered.append("Award notice (contract already awarded)")

    # Security clearance required
    clearance_patterns = [
        r'security clearance required',
        r'\bts/sci\b',
        r'\btop secret\b',
        r'secret clearance',
        r'facility clearance required',
        r'\bscif\b',
    ]
    for p in clearance_patterns:
        if re.search(p, text, re.IGNORECASE):
            triggered.append("Security clearance required")
            break

    # Ineligible set-aside
    ineligible = [s.lower().strip() for s in settings.get("ineligible_set_asides", []) if s.strip()]
    set_aside = (opp.get("set_aside") or "").lower().strip()
    if set_aside and any(ineq in set_aside or set_aside in ineq for ineq in ineligible):
        triggered.append(f"Ineligible set-aside ({opp.get('set_aside', '')})")

    # ITAR restricted (not just "may be subject to")
    if re.search(r'itar restricted|itar compliance required', text, re.IGNORECASE):
        if not re.search(r'may be subject to itar', text, re.IGNORECASE):
            triggered.append("ITAR compliance required")

    # Excessive contract value (> $2M)
    val, _ = _extract_contract_value(opp)
    if val is not None and val > 2_000_000:
        triggered.append(f"Contract value too large (${val:,.0f})")

    # Classified work
    if re.search(r'classified information|classified contract|classified program', text, re.IGNORECASE):
        triggered.append("Classified work required")

    # Weapons / ordnance
    if re.search(
        r'\bexplosives?\b|\bordnance\b|\bnuclear weapon\b|\bchemical weapon\b'
        r'|\bbiological weapon\b|\bmunitions\b'
        r'|\bgun\b|\bcannon\b|\bmissile\b|\bammunition\b',
        text, re.IGNORECASE
    ):
        triggered.append("Weapons/ordnance work")

    # OEM vendor lock
    if re.search(
        r'authorized reseller|oem partnership required|'
        r'certified\s+\w+\s+integrator|oem\s+partner\s+required',
        text, re.IGNORECASE
    ):
        triggered.append("OEM/vendor certification required")

    # Large team required (5+ FTE)
    if re.search(
        r'\b([5-9]|\d{2,})\s*(?:or more\s*)?'
        r'(?:fte|full[- ]time equivalent|full[- ]time staff|personnel|employees|staff members)\b',
        text, re.IGNORECASE
    ):
        triggered.append("Large team (5+ FTE) required")

    # Specialized facility required
    if re.search(
        r'manufacturing facility|(?<![Nn]o )cleanroom|(?<![Nn]o )clean room|'
        r'accredited laboratory|production facility',
        text, re.IGNORECASE
    ):
        triggered.append("Specialized facility required")

    # NAICS blacklist — industries we don't serve
    naics_blacklist_prefixes = [
        '314', '336110', '237', '238', '311', '312', '313',
        '621', '622', '623', '524', '522', '561', '562', '811',
    ]
    naics_code = str(opp.get("naics_code") or "")
    if naics_code and any(naics_code.startswith(p) for p in naics_blacklist_prefixes):
        triggered.append(f"Blacklisted NAICS ({naics_code})")

    return triggered


# ─────────────────────────────────────────────────────────────────────────────
# Category scorers
# ─────────────────────────────────────────────────────────────────────────────

def _score_entry_barrier(text, opp, settings):
    """Score entry barrier category. Returns (points ≤ 40, details_list)."""
    pts = 0
    details = []

    # SBIR / STTR (+12)
    is_sbir = bool(
        re.search(r'\bsbir\b|\bsttr\b', text, re.IGNORECASE)
        or re.search(r'\bsbir\b|\bsttr\b', (opp.get("type") or ""), re.IGNORECASE)
        or re.search(r'\bsbir\b|\bsttr\b', (opp.get("source") or ""), re.IGNORECASE)
    )
    if is_sbir:
        pts += 12
        details.append({"id": "sbir_sttr", "points": 12,
                         "label": "SBIR/STTR (designed for new entrants)"})

    # Set-aside eligibility (+8)
    ineligible = [s.lower().strip() for s in settings.get("ineligible_set_asides", []) if s.strip()]
    eligible   = [s.lower().strip() for s in settings.get("eligible_set_asides", []) if s.strip()]
    set_aside_raw = (opp.get("set_aside") or "").strip()
    set_aside = set_aside_raw.lower()

    if set_aside:
        ineq = any(ineq in set_aside or set_aside in ineq for ineq in ineligible)
        eq   = any(eq   in set_aside or set_aside in eq   for eq   in eligible)
        if not ineq and eq:
            pts += 8
            details.append({"id": "eligible_set_aside", "points": 8,
                             "label": f"Eligible set-aside ({set_aside_raw})"})
    else:
        # No set-aside = unrestricted = open competition
        pts += 8
        details.append({"id": "eligible_set_aside", "points": 8,
                         "label": "No set-aside (unrestricted competition)"})

    # No past performance required (+8)
    if not re.search(
        r'past performance (?:is )?required|\bcpars\b|'
        r'relevant experience required|demonstrated experience required|'
        r'past performance will be (?:heavily )?evaluated',
        text, re.IGNORECASE
    ):
        pts += 8
        details.append({"id": "no_past_performance", "points": 8,
                         "label": "Past performance not explicitly required"})

    # Explicitly new-entrant friendly (+5)
    friendly = any(re.search(p, text, re.IGNORECASE) for p in [
        r'new entrant', r'new vendor', r'emerging small business',
        r'no prior experience', r'no past performance',
    ])
    if friendly:
        pts += 5
        details.append({"id": "new_entrant_friendly", "points": 5,
                         "label": "Explicitly welcomes new vendors/entrants"})

    # Contract value tiers
    val, is_idiq = _extract_contract_value(opp)
    if is_idiq:
        details.append({"id": "idiq_warning", "points": 0,
                         "label": "IDIQ — individual task orders may be smaller than ceiling"})
    if val is not None:
        if val < 25_000:
            pts += 8
            details.append({"id": "value_micro", "points": 8,
                             "label": f"Micro-purchase (${val:,.0f}) — lowest scrutiny"})
        elif val <= 100_000:
            pts += 6
            details.append({"id": "value_small", "points": 6,
                             "label": f"Small value (${val:,.0f})"})
        elif val <= 250_000:
            pts += 4
            details.append({"id": "value_medium", "points": 4,
                             "label": f"Medium value (${val:,.0f})"})
        elif val <= 500_000:
            pts += 1
            details.append({"id": "value_large", "points": 1,
                             "label": f"Large value (${val:,.0f}) — teaming suggested"})
        else:
            pts -= 15
            details.append({"id": "value_too_large", "points": -15,
                             "label": f"Value ${val:,.0f} exceeds solo ceiling"})

    # No facility requirement (+4)
    if not re.search(
        r'facility clearance|manufacturing facility|cleanroom|clean room|laboratory required',
        text, re.IGNORECASE
    ):
        pts += 4
        details.append({"id": "no_facility", "points": 4,
                         "label": "No specialized facility required"})

    # Notice-type modifier — live bids score higher than intel-only notices
    opp_type_raw = (opp.get("type") or "").strip()
    opp_type_lower = opp_type_raw.lower()
    is_combined_synopsis = (opp_type_raw == "k" or "combined synopsis" in opp_type_lower)
    if is_combined_synopsis:
        pts += 2
        details.append({"id": "live_solicitation", "points": 2,
                         "label": "Combined Synopsis — actively biddable (reduced weight)"})
    elif any(t in opp_type_lower for t in ("solicitation",)):
        pts += 8
        details.append({"id": "live_solicitation", "points": 8,
                         "label": "Live solicitation — actively biddable"})
    elif any(t in opp_type_lower for t in ("presolicitation",)):
        pts += 4
        details.append({"id": "presolicitation", "points": 4,
                         "label": "Presolicitation — pipeline visibility"})
    elif any(t in opp_type_lower for t in ("sources sought",)):
        pts += 3
        details.append({"id": "sources_sought", "points": 3,
                         "label": "Sources Sought — respond to shape acquisition"})
    elif any(t in opp_type_lower for t in ("special notice",)):
        pts += 2
        details.append({"id": "special_notice", "points": 2,
                         "label": "Special Notice — review for relevance"})

    # BAA bonus — highest-value R&D instrument for solo operators
    if re.search(r'\bbroad agency announcement\b|\bbaa\b', text, re.IGNORECASE):
        pts += 10
        details.append({"id": "baa_instrument", "points": 10,
                         "label": "Broad Agency Announcement — ideal solo R&D instrument"})

    return max(0, min(40, pts)), details


def _score_scope_simplicity(text, opp, settings):
    """Score scope simplicity. Returns (points ≤ 25, details_list)."""
    pts = 0
    details = []

    # Study / report / prototype deliverable (+8)
    study_terms = [
        "study", "report", "analysis", "feasibility", "assessment", "design",
        "prototype", "proof of concept", "literature review", "trade study",
    ]
    study_matches = _find_matches(study_terms, text)
    if study_matches:
        pts += 8
        details.append({"id": "study_report", "points": 8,
                         "label": "Study/prototype deliverable",
                         "matches": study_matches[:4]})

    # Single-person scope — no signals of large team or multi-site (+7)
    multi_patterns = [
        r'team of \d+', r'multiple personnel', r'\bstaff of\b',
        r'\bfte\b', r'full[- ]time equivalent',
        r'multi[- ]site', r'multiple sites?\b', r'multiple locations?\b',
        r'\d+\s+sites?\b',
    ]
    if not any(re.search(p, text, re.IGNORECASE) for p in multi_patterns):
        pts += 7
        details.append({"id": "single_person", "points": 7,
                         "label": "Single-person scope (no large-team signals)"})

    # Clear, bounded deliverables — not managed services / IDIQ (+5)
    open_ended_patterns = [
        r'\bidiq\b', r'\bindefinite[- ]quantity\b', r'managed service',
        r'operations and maintenance', r'\bo&m\b',
    ]
    if not any(re.search(p, text, re.IGNORECASE) for p in open_ended_patterns):
        pts += 5
        details.append({"id": "clear_deliverables", "points": 5,
                         "label": "Clear bounded deliverables (not IDIQ/managed services)"})

    # Short period of performance (+3)
    if bool(
        re.search(r'\b([1-9]|1[01])\s*month', text, re.IGNORECASE)
        or re.search(r'phase\s+(?:i|1)\b', text, re.IGNORECASE)
    ):
        pts += 3
        details.append({"id": "short_duration", "points": 3,
                         "label": "Period of performance < 12 months"})

    # Sources Sought / RFI (+2)
    opp_type = (opp.get("type") or "").lower()
    is_ss_rfi = (
        any(t in opp_type for t in ("sources sought", "request for information", "special notice"))
        or bool(re.search(r'\b(?:sources sought|request for information|rfi)\b', text, re.IGNORECASE))
    )
    if is_ss_rfi:
        pts += 2
        details.append({"id": "sources_sought_rfi", "points": 2,
                         "label": "Sources Sought / RFI — low effort to respond"})

    return max(0, min(25, pts)), details


def _score_competition_level(text, opp, settings):
    """Score competition level. Returns (points ≤ 20, details_list)."""
    pts = 0
    details = []

    # SBIR/STTR limited pool (+8)
    is_sbir = bool(
        re.search(r'\bsbir\b|\bsttr\b', text, re.IGNORECASE)
        or re.search(r'\bsbir\b|\bsttr\b', (opp.get("type") or ""), re.IGNORECASE)
        or re.search(r'\bsbir\b|\bsttr\b', (opp.get("source") or ""), re.IGNORECASE)
    )
    if is_sbir:
        pts += 8
        details.append({"id": "sbir_pool", "points": 8,
                         "label": "SBIR/STTR — limited innovation-focused competitor pool"})

    # Eligible small business set-aside limits competition (+4)
    eligible  = [s.lower().strip() for s in settings.get("eligible_set_asides", []) if s.strip()]
    set_aside = (opp.get("set_aside") or "").lower().strip()
    if set_aside and any(eq in set_aside or set_aside in eq for eq in eligible):
        pts += 4
        details.append({"id": "sb_set_aside", "points": 4,
                         "label": "Small business set-aside limits competition"})

    # Not a recompete with an established incumbent (+5)
    recompete_patterns = [
        r'\bincumbent\b', r'\brecompete\b', r'\bfollow[- ]on\b',
        r'\bbridge contract\b', r'\bsuccessor\b',
    ]
    if not any(re.search(p, text, re.IGNORECASE) for p in recompete_patterns):
        pts += 5
        details.append({"id": "not_recompete", "points": 5,
                         "label": "Not a recompete (no established incumbent)"})

    # Niche topic reduces competitors (+3)
    niche_terms = [
        "robotics", "mechatronics", "microfluidic", "actuator", "electroactive",
        "compliant mechanism", "haptic", "soft robot", "electroosmotic",
    ]
    niche_matches = _find_matches(niche_terms, text)
    if niche_matches:
        pts += 3
        details.append({"id": "niche_topic", "points": 3,
                         "label": "Niche topic limits competitor pool",
                         "matches": niche_matches[:3]})

    return max(0, min(20, pts)), details


def _is_parts_procurement(text, opp):
    """
    Returns True if the opportunity is a commodity/parts purchase rather than
    a services/R&D contract. These are structural false positives for technical
    keyword matching.
    """
    title = (opp.get("title") or "").strip()
    naics = str(opp.get("naics_code") or "")

    # NSN pattern: digits-digits-digits-digits in title
    if re.search(r'\b\d{4}-\d{2}-\d{3}-\d{4}\b', title):
        return True

    # FSC/NIIN coded title: "XX--COMPONENT NAME" (e.g., "48--ACTUATOR,ELECTRO-ME")
    if re.match(r'^\d{2}--', title):
        return True

    # Repair/overhaul of a specific part (not R&D)
    if re.search(r'\bin repair/modification of\b|\boverhaul of\b|\brepair of\b', title, re.IGNORECASE):
        if not re.search(r'\br&d\b|\bresearch\b|\bdevelopment\b|\bprototype\b|\bstudy\b', text, re.IGNORECASE):
            return True

    # NAICS codes that are commodity manufacturing, not services/R&D
    parts_naics_prefixes = (
        "3329", "3336", "3341", "3342", "3343", "3344",
        "3325", "3326", "3327", "3328",
        "3339", "3331", "3332", "3333",
        "2381", "2382", "2383",
        "5629",
        "5621", "5622",
    )
    if any(naics.startswith(p) for p in parts_naics_prefixes):
        return True

    return False


def _score_skill_match(text, opp, keywords_cfg):
    """Score skill match. Returns (points ≤ 25, details_list)."""
    pts = 0
    details = []

    tier1 = keywords_cfg.get("positive_keywords_tier1", {}).get("terms", [])
    tier2 = keywords_cfg.get("positive_keywords_tier2", {}).get("terms", [])
    tier3 = keywords_cfg.get("positive_keywords_tier3", {}).get("terms", [])

    t1_matches = _find_matches(tier1, text)
    if t1_matches:
        pts += 15
        details.append({"id": "direct_skill", "points": 15,
                         "label": "Direct skill match (Tier 1)",
                         "matches": t1_matches[:5]})

    t2_matches = _find_matches(tier2, text)
    if t2_matches:
        pts += 8
        details.append({"id": "adjacent_skill", "points": 8,
                         "label": "Adjacent skill match (Tier 2)",
                         "matches": t2_matches[:5]})

    if not t1_matches and not t2_matches:
        t3_matches = _find_matches(tier3, text)
        if t3_matches:
            pts += 3
            details.append({"id": "generic_skill", "points": 3,
                             "label": "Generic skill match (Tier 3)",
                             "matches": t3_matches[:3]})

    # Negative keyword penalty: -5 per match, capped at -15
    negative = keywords_cfg.get("negative_keywords", {}).get("terms", [])
    neg_matches = _find_matches(negative, text)
    if neg_matches:
        neg_pts = max(-15, -5 * len(neg_matches))
        pts += neg_pts
        details.append({"id": "negative_signal", "points": neg_pts,
                         "label": "Negative signals detected",
                         "matches": neg_matches[:3]})

    return max(0, min(25, pts)), details


# ─────────────────────────────────────────────────────────────────────────────
# Warnings
# ─────────────────────────────────────────────────────────────────────────────

def _check_warnings(text, keywords_cfg):
    """Return list of triggered warning strings."""
    terms = keywords_cfg.get("warning_keywords", {}).get("terms", [])
    return _find_matches(terms, text)


# ─────────────────────────────────────────────────────────────────────────────
# Rationale generator
# ─────────────────────────────────────────────────────────────────────────────

def _generate_rationale(entry, scope, comp, skill, warnings):
    positives, negatives = [], []
    if entry >= 28:
        positives.append("low entry barrier")
    elif entry <= 12:
        negatives.append("high entry barrier")
    if skill >= 15:
        positives.append("direct skill match")
    elif skill >= 8:
        positives.append("adjacent skill match")
    elif skill == 0:
        negatives.append("no skill match")
    if scope >= 18:
        positives.append("simple scope")
    elif scope <= 6:
        negatives.append("complex/open-ended scope")
    if comp >= 15:
        positives.append("limited competition")
    parts = []
    if positives:
        parts.append("Strengths: " + ", ".join(positives))
    if negatives:
        parts.append("Concerns: " + ", ".join(negatives))
    if warnings:
        parts.append("Warnings: " + ", ".join(warnings[:2]))
    return " | ".join(parts) if parts else "No strong signals either way"


# ─────────────────────────────────────────────────────────────────────────────
# Main entry points
# ─────────────────────────────────────────────────────────────────────────────

def score_opportunity(opportunity):
    """
    Score a single opportunity.
    Returns (score, breakdown_dict, flags_list, status_str, disqualifier_reason_or_None).
    """
    keywords_cfg = _load_json("keywords.json")
    settings     = _load_json("settings.json")

    title = (opportunity.get("title") or "").lower()
    desc  = (opportunity.get("description") or "").lower()
    text  = f"{title} {desc}"

    # Step 1: Hard disqualifiers
    disqs = check_hard_disqualifiers(text, opportunity, settings)
    if disqs:
        breakdown = {
            "entry_barrier":     {"points": 0, "max": 40, "details": []},
            "scope_simplicity":  {"points": 0, "max": 25, "details": []},
            "competition_level": {"points": 0, "max": 20, "details": []},
            "skill_match":       {"points": 0, "max": 15, "details": []},
            "rationale":    f"Auto-SKIP: {disqs[0]}",
            "disqualifiers": disqs,
            "warnings":      [],
        }
        return 0, breakdown, [f"SKIP: {disqs[0]}"], "SKIP", disqs[0]

    # Step 2: Score each category
    entry_pts, entry_det = _score_entry_barrier(text, opportunity, settings)
    scope_pts, scope_det = _score_scope_simplicity(text, opportunity, settings)
    comp_pts,  comp_det  = _score_competition_level(text, opportunity, settings)

    # Suppress keyword score for parts/commodity procurement false positives
    if _is_parts_procurement(text, opportunity):
        skill_pts = 0
        skill_det = [{"id": "parts_procurement", "points": 0,
                       "label": "Parts/commodity procurement — keyword match suppressed"}]
    else:
        skill_pts, skill_det = _score_skill_match(text, opportunity, keywords_cfg)

    total = entry_pts + scope_pts + comp_pts + skill_pts

    # Priority agency bonus
    priority_agencies = settings.get("priority_agencies", [])
    agency_bonus = settings.get("priority_agency_score_bonus", 0)
    if priority_agencies and agency_bonus:
        agency_str = (opportunity.get("agency") or "").upper()
        if any(pa.upper() in agency_str for pa in priority_agencies):
            total += agency_bonus

    total = min(100, total)

    # Age decay: penalize old/closed opportunities
    deadline_str = opportunity.get("response_deadline") or ""
    if deadline_str:
        try:
            dl = None
            for fmt, length in [("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10), ("%m/%d/%Y", 10)]:
                try:
                    dl = datetime.strptime(str(deadline_str)[:length], fmt)
                    break
                except ValueError:
                    continue
            if dl is not None:
                days_overdue = (datetime.now() - dl).days
                if days_overdue > 90:
                    total = max(0, total - 30)
                elif days_overdue > 30:
                    total = max(0, total - 15)
                elif days_overdue > 7:
                    total = max(0, total - 8)
                elif days_overdue > 0:
                    total = max(0, total - 3)
        except Exception:
            pass

    # Step 3: Warnings
    warnings = _check_warnings(text, keywords_cfg)

    # Step 4: Status
    if total >= 75:
        status = "REVIEW"
    elif total >= 60:
        status = "MAYBE"
    else:
        status = "LOW"

    # Step 5: Breakdown
    breakdown = {
        "entry_barrier":     {"points": entry_pts, "max": 40, "details": entry_det},
        "scope_simplicity":  {"points": scope_pts, "max": 25, "details": scope_det},
        "competition_level": {"points": comp_pts,  "max": 20, "details": comp_det},
        "skill_match":       {"points": skill_pts, "max": 25, "details": skill_det},
        "rationale":    _generate_rationale(entry_pts, scope_pts, comp_pts, skill_pts, warnings),
        "disqualifiers": [],
        "warnings":      warnings,
    }

    flags = []
    if warnings:
        flags.extend(f"WARN: {w}" for w in warnings)
    for d in skill_det:
        if d["id"] == "direct_skill" and d.get("matches"):
            flags.append(f"MATCH: {', '.join(d['matches'][:3])}")

    return total, breakdown, flags, status, None


def categorize_opportunity(opportunity: dict, config: dict) -> str:
    """
    Returns 'engineering', 'general', or 'uncategorized'.
    Primary signal: NAICS code on the opportunity.
    Fallback: keyword matching on title/description.
    """
    naics = str(opportunity.get("naics_code", "")).strip()
    engineering_naics = config.get("naics_categories", {}).get("engineering", [])
    general_naics = config.get("naics_categories", {}).get("general", [])

    if naics in engineering_naics:
        return "engineering"
    if naics in general_naics:
        return "general"

    # Fallback: keyword-based classification when NAICS is missing or unlisted
    text = f"{opportunity.get('title', '')} {opportunity.get('description', '')}".lower()

    engineering_signals = [
        "engineering", "firmware", "embedded", "prototype", "cad",
        "3d print", "sensor", "robotics", "mechatronics", "microcontroller",
        "control system", "actuator", "r&d", "research and development",
        "python", "software development", "data processing", "modeling",
        "simulation", "instrumentation", "mapping", "surveying", "drone"
    ]
    general_signals = [
        "photography", "graphic design", "training course", "curriculum",
        "technical writing", "documentation", "video production",
        "market research", "data entry", "web content", "illustration"
    ]

    eng_hits = sum(1 for kw in engineering_signals if kw in text)
    gen_hits = sum(1 for kw in general_signals if kw in text)

    if eng_hits > gen_hits:
        return "engineering"
    if gen_hits > eng_hits:
        return "general"
    return "uncategorized"


def score_all(opportunities):
    """Score all opportunities in-place. Respects human-set statuses."""
    settings = _load_json("settings.json")
    for opp in opportunities:
        score, breakdown, flags, computed_status, disq_reason = score_opportunity(opp)
        opp["score"]          = score
        opp["score_breakdown"] = breakdown
        opp["flags"]          = flags
        # Hard disqualifiers always override; human-set statuses are preserved otherwise
        current = opp.get("status")
        if computed_status == "SKIP":
            opp["status"] = "SKIP"
        elif current not in USER_STATUSES:
            opp["status"] = computed_status
        if disq_reason:
            opp["disqualifier_reason"] = disq_reason
        elif "disqualifier_reason" not in opp:
            opp["disqualifier_reason"] = None
        # Set category if not already set by a human/prior run
        if not opp.get("category"):
            opp["category"] = categorize_opportunity(opp, settings)
    return opportunities
