"""SBIR.gov scraper using their current API."""

import logging
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# SBIR.gov GraphQL endpoint
SBIR_API_BASE = "https://www.sbir.gov/api/sbirsearch/topic"


class SbirGovScraper(BaseScraper):
    def __init__(self):
        super().__init__("SBIR.gov", rate_limit_seconds=2.0)

    def search(self, keywords, naics_codes, set_asides):
        """Search SBIR/STTR opportunities."""
        opportunities = []

        # Try the topic search API
        for keyword in keywords[:3]:
            params = {
                "keyword": keyword,
                "rows": 25,
            }
            data = self.fetch_json(SBIR_API_BASE, params=params)
            if data and isinstance(data, list):
                for sol in data:
                    opportunities.append(self._parse(sol))
            elif data and isinstance(data, dict):
                for sol in data.get("topics", data.get("results", [])):
                    opportunities.append(self._parse(sol))

        # Fallback: try open solicitations endpoint
        if not opportunities:
            open_url = "https://www.sbir.gov/api/sbirsearch/solicitation/open"
            data = self.fetch_json(open_url)
            if data and isinstance(data, list):
                for sol in data[:50]:
                    opportunities.append(self._parse(sol))

        # Dedupe
        seen = set()
        deduped = []
        for o in opportunities:
            if o["id"] and o["id"] not in seen:
                seen.add(o["id"])
                deduped.append(o)

        logger.info(f"[SBIR.gov] Found {len(deduped)} opportunities")
        return deduped

    def _parse(self, sol):
        # Handle various response formats
        sol_id = sol.get("topicId") or sol.get("solicitationId") or sol.get("id") or ""
        title = sol.get("topicTitle") or sol.get("solicitationTitle") or sol.get("title") or ""

        return self._normalize_opportunity(
            id=f"SBIR-{sol_id}" if sol_id else "",
            title=title,
            agency=sol.get("agency") or sol.get("component") or "",
            office=sol.get("branch") or sol.get("program") or "",
            description=sol.get("abstract") or sol.get("description") or sol.get("topicDescription") or "",
            type="SBIR/STTR",
            posted_date=sol.get("openDate") or sol.get("postedDate") or "",
            response_deadline=sol.get("closeDate") or sol.get("deadline") or sol.get("proposalEndDate") or "",
            url=sol.get("url") or sol.get("solicitationUrl") or f"https://www.sbir.gov/node/{sol_id}" if sol_id else "",
            set_aside="Small Business",
        )
