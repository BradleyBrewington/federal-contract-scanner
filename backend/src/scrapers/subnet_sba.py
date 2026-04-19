"""
SubNet SBA scraper — subcontracting opportunities from large prime contractors.
SubNet has no public API. This scraper parses the web interface.
Run every 48 hours (less frequent than SAM.gov since SubNet updates slowly).
"""

import requests
from bs4 import BeautifulSoup
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)

SUBNET_BASE = "https://subnet.sba.gov/client/dsp_Landing.cfm"

SEARCH_KEYWORDS = [
    "engineering", "robotics", "sensor", "prototype", "embedded",
    "firmware", "CAD", "mechanical", "electrical", "controls",
    "automation", "instrumentation", "software", "data", "drone",
    "photography", "training", "documentation", "graphic"
]


def scrape_subnet() -> list:
    """
    Scrapes SubNet for subcontracting opportunities matching target keywords.
    Returns list of opportunity dicts normalized to match SAM.gov schema.
    Fails gracefully — logs errors and returns whatever was collected so far.
    """
    opportunities = []
    seen_ids = set()

    session = requests.Session()
    session.headers.update({"User-Agent": "FederalContractScanner/1.0"})

    for keyword in SEARCH_KEYWORDS:
        try:
            params = {
                "searchText": keyword,
                "searchType": "keyword",
                "Submit": "Search"
            }
            response = session.get(SUBNET_BASE, params=params, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Parse opportunity rows — adjust selectors if SubNet layout changes
            rows = soup.find_all("tr", class_=["odd", "even"])
            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue

                title = cells[0].get_text(strip=True)
                company = cells[1].get_text(strip=True)
                deadline = cells[2].get_text(strip=True)
                description = cells[3].get_text(strip=True)

                if not title:
                    continue

                # Generate stable ID from title + company
                opp_id = hashlib.md5(f"{title}{company}".encode()).hexdigest()[:12]
                if opp_id in seen_ids:
                    continue
                seen_ids.add(opp_id)

                opportunities.append({
                    "id": f"SUBNET-{opp_id}",
                    "source": "SubNet",
                    "title": title,
                    "agency": company,  # Prime contractor name
                    "office": "",
                    "description": description,
                    "close_date": deadline,
                    "naics_code": "",   # SubNet often omits NAICS
                    "set_aside": "",
                    "type": "Subcontracting Opportunity",
                    "posted_date": "",
                    "response_deadline": deadline,
                    "estimated_value": "",
                    "contract_value_min": 0,
                    "contract_value_max": 0,
                    "url": SUBNET_BASE,
                    "attachments": [],
                    "contact": "",
                    "place_of_performance": "",
                    "scraped_at": datetime.utcnow().isoformat(),
                    "status": "new",
                    "score": 0,
                    "score_breakdown": {},
                    "flags": [],
                    "ai_summary": "",
                    "ai_requirements": "",
                    "ai_feasibility": "",
                    "ai_red_flags": "",
                    "ai_recommendation": "",
                    "notes": "",
                    "teaming_leads": [],
                })

        except Exception as e:
            logger.error(f"SubNet scrape error for keyword '{keyword}': {e}")
            continue

    logger.info(f"[SubNet] Collected {len(opportunities)} opportunities")
    return opportunities
