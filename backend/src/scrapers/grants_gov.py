"""Grants.gov scraper."""

import logging
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

GRANTS_API_BASE = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"


class GrantsGovScraper(BaseScraper):
    def __init__(self):
        super().__init__("Grants.gov", rate_limit_seconds=2.0)

    def search(self, keywords, naics_codes, set_asides):
        opportunities = []

        for keyword in keywords[:5]:
            payload = {"keyword": keyword, "oppStatuses": "forecasted|posted", "rows": 50, "sortBy": "openDate|desc"}
            self._rate_limit()
            try:
                resp = self.session.post(GRANTS_API_BASE, json=payload, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"[Grants.gov] Search failed for '{keyword}': {e}")
                continue

            for opp in data.get("oppHits", []):
                opportunities.append(self._parse(opp))

        seen = set()
        deduped = []
        for o in opportunities:
            if o["id"] not in seen:
                seen.add(o["id"])
                deduped.append(o)
        return deduped

    def _parse(self, opp):
        return self._normalize_opportunity(
            id=f"GRANT-{opp.get('id', opp.get('oppNumber', ''))}",
            title=opp.get("title", opp.get("oppTitle", "")),
            agency=opp.get("agency", opp.get("agencyName", "")),
            office=opp.get("office", ""),
            description=opp.get("description", opp.get("synopsis", "")),
            type="Grant",
            posted_date=opp.get("openDate", ""),
            response_deadline=opp.get("closeDate", ""),
            url=f"https://www.grants.gov/search-results-detail/{opp.get('id', opp.get('oppNumber', ''))}",
            estimated_value=opp.get("awardCeiling", ""),
        )
