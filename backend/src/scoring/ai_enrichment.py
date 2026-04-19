"""Claude API enrichment — GO/NO-GO assessment for high-scoring opportunities."""

import json
import os
import re
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are evaluating a federal contract opportunity for a specific person. Your job is to give a brutally honest GO/NO-GO assessment.

THE PERSON:
- Founder and principal engineer of Icarus Dynamics LLC
- LLC formed March 2026, SAM.gov registration pending
- First-time federal contractor — zero past performance, no CPARS
- No security clearance, no facility clearance
- Home-based — no lab, no manufacturing facility, no cleanroom
- No employees (can hire 1 consultant max)
- Located in Bryan/College Station, Texas
- SBIR/STTR eligible under NAICS 541715

SKILLS:
- CAD (Fusion 360, OpenSCAD), 3D printing (PETG/PLA), PCB design (KiCad)
- Arduino/microcontroller programming, embedded systems
- Soft robotics, compliant mechanisms, control systems
- Electroosmotic pump (EOP) development and testing, fluidic actuation
- Ballast water treatment concepts, electrochemical systems
- Technical writing, data analysis, Python scripting
- Research and literature review

PRIMARY R&D FOCUS:
- Electroosmotic pump (EOP) actuation for soft robotics, human performance,
  and environmental applications (ballast water treatment)
- If EOP or fluidic actuation is a plausible technical approach for an
  opportunity — even if not stated explicitly — flag this as a GO signal

CANNOT DO:
- Classified work, ITAR-restricted work
- Enterprise IT deployment, systems integration
- Large-scale manufacturing or production
- Multi-site installation or deployment
- Work requiring specific vendor certifications or OEM partnerships
- Work requiring teams of 3+ people
- Work requiring specific professional licenses (PE, PMP, etc.)

SET-ASIDE ELIGIBILITY:
- CAN compete: Total Small Business, Partial Small Business, Unrestricted, SBIR/STTR
- CANNOT compete: SDVOSB, VOSB, 8(a), HUBZone, WOSB, EDWOSB

GO/NO-GO RUBRIC — reward these highly:
- Broad Agency Announcements (BAAs) — no contract competition, merit-based
- Sources Sought from ONR, Navy, Army, NASA — respond to shape the acquisition
- Technology transfer licensing opportunities (NAICS 927110)
- Prize competitions with no teaming requirement
- Any opportunity where EOP or fluidic actuation is a plausible technical approach

Respond in this exact JSON format (no markdown, no extra text):
{
  "go_no_go": "GO",
  "confidence": 0.8,
  "summary": "2-3 sentence plain English description of what the government actually wants",
  "requirements": ["list item 1", "list item 2"],
  "dealbreakers": [],
  "warnings": [],
  "feasibility": "TARGET \u2014 1-sentence justification",
  "recommended_action": "Specific next step for this person",
  "estimated_effort_hours": 10,
  "teaming_needed": false
}

go_no_go must be exactly "GO" or "NO-GO".
feasibility must start with exactly one of: SAFE, TARGET, REACH, SKIP.
Be harsh. If this person cannot win or perform this contract, say NO-GO. Do not sugarcoat."""


def _get_client():
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    except Exception as e:
        logger.error(f"Failed to create Anthropic client: {e}")
        return None


def _parse_json_response(text):
    """Parse JSON from Claude response, stripping markdown fences if present."""
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return json.loads(text.strip())


def enrich_opportunity(opportunity, attachment_text=""):
    """Call Claude to produce GO/NO-GO assessment. Updates opportunity in-place."""
    if opportunity.get("status") == "SKIP":
        return opportunity

    client = _get_client()
    if not client:
        return opportunity

    title    = opportunity.get("title", "")
    agency   = opportunity.get("agency", "")
    notice   = opportunity.get("type", "")
    aside    = opportunity.get("set_aside", "") or "None"
    naics    = opportunity.get("naics_code", "") or "Not specified"
    value    = opportunity.get("estimated_value", "") or "Not specified"
    deadline = opportunity.get("response_deadline", "") or "Not specified"
    pop      = opportunity.get("place_of_performance", "") or "Not specified"
    desc     = (opportunity.get("description") or "")[:3000]

    user_message = (
        f"Evaluate this opportunity:\n\n"
        f"Title: {title}\n"
        f"Agency: {agency}\n"
        f"Notice Type: {notice}\n"
        f"Set-Aside: {aside}\n"
        f"NAICS: {naics}\n"
        f"Estimated Value: {value}\n"
        f"Response Deadline: {deadline}\n"
        f"Place of Performance: {pop}\n\n"
        f"Description:\n{desc}"
    )
    if attachment_text:
        user_message += f"\n\nAttachment Text (if available):\n{attachment_text[:2000]}"

    try:
        response = _get_client().messages.create(
            model="claude-opus-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        raw  = response.content[0].text
        data = _parse_json_response(raw)

        opportunity["ai_go_no_go"]       = data.get("go_no_go", "")
        opportunity["ai_confidence"]     = data.get("confidence", 0.0)
        opportunity["ai_summary"]        = data.get("summary", "")
        opportunity["ai_requirements"]   = "\n".join(f"\u2022 {r}" for r in (data.get("requirements") or []))
        opportunity["ai_red_flags"]      = "\n".join(f"\u2022 {d}" for d in (data.get("dealbreakers") or []))
        opportunity["ai_warnings_list"]  = data.get("warnings", [])
        opportunity["ai_feasibility"]    = data.get("feasibility", "")
        opportunity["ai_recommendation"] = data.get("recommended_action", "")
        opportunity["ai_effort_hours"]   = data.get("estimated_effort_hours", 0)
        opportunity["ai_teaming_needed"] = data.get("teaming_needed", False)

    except json.JSONDecodeError as e:
        logger.warning(f"AI response not valid JSON for '{title}': {e}. Storing raw text.")
        opportunity["ai_summary"] = raw[:500] if 'raw' in dir() else ""
    except Exception as e:
        logger.error(f"AI enrichment failed for '{title}': {e}")

    return opportunity


def enrich_all(opportunities, score_threshold=50, attachment_texts=None):
    """Enrich opportunities at or above threshold, skipping SKIP-status ones."""
    attachment_texts = attachment_texts or {}
    enriched_count = 0
    for opp in opportunities:
        if opp.get("status") == "SKIP":
            continue
        if opp.get("score", 0) < score_threshold:
            continue
        if opp.get("ai_go_no_go") and not opp.get("force_reenrich"):
            continue
        att_text = attachment_texts.get(opp["id"], "")
        enrich_opportunity(opp, attachment_text=att_text)
        opp.pop("force_reenrich", None)
        enriched_count += 1
    logger.info(f"AI-enriched {enriched_count} opportunities")
    return opportunities
