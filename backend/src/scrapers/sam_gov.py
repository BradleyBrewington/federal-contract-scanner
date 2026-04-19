"""SAM.gov opportunities API scraper - optimized for rate limits."""

import os
import logging
from datetime import datetime, timedelta
from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)

SAM_API_BASE = "https://api.sam.gov/opportunities/v2/search"


class SamGovScraper(BaseScraper):
    def __init__(self):
        super().__init__("SAM.gov", rate_limit_seconds=2.0)
        self.api_key = os.getenv("SAM_API_KEY", "")

    def search(self, keywords, naics_codes, set_asides):
        """
        Two-mode search:
        - If naics_codes provided: broad fetch with ncode anchor for first NAICS,
          filter all results client-side by full NAICS set.
        - If keywords provided (no naics_codes): send keywords as 'q' param to API
          for targeted keyword-based fetch with no client-side NAICS filter.

        SAM.gov API v2 'q' param: freetext search across title, description, agency.
        Public API keys are limited to 10 requests/day.
        """
        if not self.api_key:
            logger.error("SAM_API_KEY not set")
            return []

        opportunities = []
        naics_set = set(naics_codes) if naics_codes else set()
        posted_from = (datetime.now() - timedelta(days=7)).strftime("%m/%d/%Y")
        posted_to = datetime.now().strftime("%m/%d/%Y")

        params = {
            "api_key": self.api_key,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": 1000,
            "offset": 0,
        }

        if keywords and not naics_set:
            # Keyword pass: send top 10 Tier-1 terms as 'q' (SAM treats as OR)
            top_keywords = keywords[:10]
            params["q"] = " ".join(
                f'"{kw}"' if " " in kw else kw for kw in top_keywords
            )
            logger.info(f"[SAM.gov] Keyword search: q={params['q']!r}")
        elif naics_set:
            # NAICS pass: anchor on first code to help API narrow results,
            # still filter all results client-side for the full NAICS set
            first_naics = next(iter(sorted(naics_set)))
            params["ncode"] = first_naics
            logger.info(
                f"[SAM.gov] NAICS anchor: {first_naics}, "
                f"filtering {len(naics_set)} codes client-side"
            )

        logger.info(f"[SAM.gov] Fetching opportunities ({posted_from} to {posted_to})...")
        data = self.fetch_json(SAM_API_BASE, params=params)

        if not data:
            return []

        # Check for rate limit
        if isinstance(data, dict) and data.get("code") == "900804":
            next_time = data.get("nextAccessTime", "unknown")
            logger.error(f"[SAM.gov] Rate limited until {next_time}")
            return []

        total = data.get("totalRecords", 0)
        fetched = data.get("opportunitiesData", [])
        logger.info(f"[SAM.gov] Found {total} total records, fetched {len(fetched)} in this page")

        # Paginate to get more results (each page costs 1 of 10 daily API calls)
        max_pages = 5  # Cap at 5 total requests to stay within daily quota
        all_raw = list(fetched)
        pages_used = 1
        while len(all_raw) < total and pages_used < max_pages:
            params["offset"] = len(all_raw)
            logger.info(f"[SAM.gov] Fetching page at offset {params['offset']} (request {pages_used + 1}/{max_pages})...")
            page_data = self.fetch_json(SAM_API_BASE, params=params)
            if not page_data or not page_data.get("opportunitiesData"):
                break
            all_raw.extend(page_data["opportunitiesData"])
            pages_used += 1
        if len(all_raw) < total:
            logger.info(f"[SAM.gov] Fetched {len(all_raw)} of {total} total (capped to conserve API quota)")

        # Filter by NAICS client-side if codes are configured
        for opp in all_raw:
            if naics_set:
                opp_naics = opp.get("naicsCode", "")
                opp_naics_list = opp.get("naicsCodes") or []
                if opp_naics not in naics_set and not (set(opp_naics_list) & naics_set):
                    continue
            opportunities.append(self._parse_opportunity(opp))

        logger.info(f"[SAM.gov] Parsed {len(opportunities)} opportunities (from {len(all_raw)} total, filtered by {len(naics_set)} NAICS codes)")
        return opportunities

    def _parse_opportunity(self, opp):
        attachments = []
        for res in (opp.get("resourceLinks") or []):
            if isinstance(res, str):
                attachments.append(res)

        # Extract description from multiple possible fields
        description = opp.get("description", "")
        if not description:
            description = opp.get("additionalInfoLink", "") or opp.get("title", "")

        return self._normalize_opportunity(
            id=f"SAM-{opp.get('noticeId', '')}",
            title=opp.get("title", ""),
            agency=opp.get("fullParentPathName", "").split(".")[0] if opp.get("fullParentPathName") else opp.get("department", ""),
            office=opp.get("fullParentPathName", "").split(".")[-1] if opp.get("fullParentPathName") else "",
            description=description,
            naics_code=opp.get("naicsCode", ""),
            set_aside=opp.get("typeOfSetAside", "") or opp.get("typeOfSetAsideDescription", ""),
            type=opp.get("type", ""),
            posted_date=opp.get("postedDate", ""),
            response_deadline=opp.get("responseDeadLine", ""),
            url=f"https://sam.gov/opp/{opp.get('noticeId', '')}/view",
            estimated_value=self._extract_value(opp),
            attachments=attachments,
            contact=self._extract_contact(opp),
            place_of_performance=self._extract_location(opp),
        )

    def _extract_value(self, opp):
        if isinstance(opp.get("award"), dict):
            return opp["award"].get("amount", "")
        return ""

    def _extract_contact(self, opp):
        contacts = opp.get("pointOfContact", [])
        if contacts and isinstance(contacts, list) and len(contacts) > 0:
            c = contacts[0]
            return f"{c.get('fullName', '')} - {c.get('email', '')}".strip(" -")
        return ""

    def _extract_location(self, opp):
        pop = opp.get("placeOfPerformance", {})
        if isinstance(pop, dict):
            state = pop.get("state", {})
            if isinstance(state, dict):
                return state.get("name", "")
        return ""
