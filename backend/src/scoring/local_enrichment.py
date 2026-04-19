"""Local LLM enrichment using Ollama for brief summaries."""

import os
import logging
import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")  # or mistral, phi3, etc.


def is_ollama_available():
    """Check if Ollama is running."""
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def get_brief_summary(title, description, agency="", max_length=150):
    """Generate a brief 1-2 sentence summary using local LLM."""
    # If no description, create summary from title
    if not description or len(description) < 50:
        if title:
            prompt = f"""Based on this federal opportunity title, write a brief 1-sentence explanation of what this opportunity is likely seeking. Be specific.

Title: {title}
Agency: {agency}

Brief explanation (1 sentence):"""
        else:
            return ""
    else:
        prompt = f"""Summarize this federal opportunity in 1-2 short sentences. Be specific about what they need.

Title: {title}
Description: {description[:1500]}

Brief summary (1-2 sentences):"""

    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 100, "temperature": 0.3}
            },
            timeout=30
        )
        if resp.status_code == 200:
            result = resp.json().get("response", "").strip()
            # Clean up the response
            result = result.replace("\n", " ").strip()
            if len(result) > 10:
                return result[:300]
    except Exception as e:
        logger.debug(f"Ollama summary failed: {e}")

    # Fallback: return truncated description
    return description[:max_length].rsplit(' ', 1)[0] + "..." if len(description) > max_length else description


def extract_key_info(description):
    """Extract key information from description without AI."""
    import re

    info = {}

    # Dollar amounts
    money_pattern = r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|M|B|k|K))?|\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:million|billion|dollars)'
    amounts = re.findall(money_pattern, description, re.IGNORECASE)
    if amounts:
        info["amounts"] = amounts[:3]

    # Dates
    date_pattern = r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}'
    dates = re.findall(date_pattern, description, re.IGNORECASE)
    if dates:
        info["dates"] = dates[:3]

    # Requirements keywords
    req_keywords = ["must have", "required", "minimum", "experience", "certification", "clearance", "years"]
    found_reqs = [kw for kw in req_keywords if kw.lower() in description.lower()]
    if found_reqs:
        info["has_requirements"] = True

    # Contract type hints
    if any(x in description.lower() for x in ["idiq", "bpa", "task order"]):
        info["contract_type"] = "IDIQ/BPA"
    elif "firm fixed" in description.lower() or "ffp" in description.lower():
        info["contract_type"] = "Fixed Price"
    elif "cost plus" in description.lower() or "cpff" in description.lower():
        info["contract_type"] = "Cost Plus"

    return info


def enrich_with_local_llm(opportunities, force=False):
    """Add brief summaries to all opportunities using Ollama."""
    if not is_ollama_available():
        logger.warning("Ollama not available - using text extraction only")
        use_ollama = False
    else:
        logger.info(f"Ollama available, using model: {OLLAMA_MODEL}")
        use_ollama = True

    count = 0
    for opp in opportunities:
        # Skip if already has a summary (from Claude)
        if opp.get("ai_summary") and not force:
            continue

        # Extract key info (always do this - it's free)
        key_info = extract_key_info(opp.get("description", ""))
        opp["extracted_info"] = key_info

        # Get brief summary
        if use_ollama:
            summary = get_brief_summary(
                opp.get("title", ""),
                opp.get("description", ""),
                opp.get("agency", "")
            )
            if summary:
                opp["brief_summary"] = summary
                count += 1
        else:
            # Fallback: truncate description or use title
            desc = opp.get("description", "")
            if desc:
                opp["brief_summary"] = desc[:200].rsplit(' ', 1)[0] + "..." if len(desc) > 200 else desc
            elif opp.get("title"):
                opp["brief_summary"] = f"Opportunity: {opp['title']}"

    logger.info(f"Local enrichment complete: {count} Ollama summaries generated")
    return opportunities
