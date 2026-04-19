"""USASpending.gov teaming lead search."""

import logging
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

USASPENDING_BASE = "https://api.usaspending.gov/api/v2"


class USASpendingScraper(BaseScraper):
    def __init__(self):
        super().__init__("USASpending", rate_limit_seconds=1.5)

    def search(self, keywords, naics_codes, set_asides):
        """Not used for opportunity search; use find_teaming_leads instead."""
        return []

    def find_teaming_leads(self, naics_code, agency=None, limit=5):
        """Find top contractors by NAICS code for teaming purposes."""
        filters = {"naics_codes": [{"code": naics_code}]} if naics_code else {}
        if agency:
            filters["agencies"] = [{"type": "awarding", "name": agency}]

        payload = {
            "filters": filters,
            "category": "recipient",
            "limit": limit,
            "page": 1,
            "subawards": False,
        }

        self._rate_limit()
        try:
            resp = self.session.post(
                f"{USASPENDING_BASE}/search/spending_by_category/",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[USASpending] Teaming search failed: {e}")
            return []

        leads = []
        for r in data.get("results", [])[:limit]:
            lead = {
                "name": r.get("name", "Unknown"),
                "amount": r.get("amount", 0),
                "count": r.get("count", 0),
                "naics_code": naics_code,
            }
            # Try to get contact info
            recipient_id = r.get("recipient_id")
            if recipient_id:
                detail = self._get_recipient_detail(recipient_id)
                if detail:
                    lead["location"] = detail.get("location", {}).get("address_line1", "")
                    lead["state"] = detail.get("location", {}).get("state_code", "")
                    lead["duns"] = detail.get("duns", "")
                    lead["cage_code"] = detail.get("cage_code", "")
            leads.append(lead)

        return leads

    def _get_recipient_detail(self, recipient_id):
        data = self.fetch_json(f"{USASPENDING_BASE}/recipient/{recipient_id}/")
        return data
