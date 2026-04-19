"""Base scraper with common fetch/retry/rate-limit logic."""

import time
import logging
import requests
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base for all opportunity scrapers."""

    def __init__(self, name, rate_limit_seconds=1.0, max_retries=3):
        self.name = name
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self._last_request_time = 0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "FederalContractScanner/1.0"
        })

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_time = time.time()

    def fetch(self, url, params=None, headers=None):
        """GET with retry and rate limiting."""
        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=30)
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                logger.warning(f"[{self.name}] Attempt {attempt}/{self.max_retries} failed: {e}")
                # Don't retry on 429 rate limit — it won't resolve by retrying
                if hasattr(e, 'response') and e.response is not None and e.response.status_code == 429:
                    logger.error(f"[{self.name}] Rate limited (429). Stopping requests.")
                    return None
                if attempt == self.max_retries:
                    logger.error(f"[{self.name}] All retries exhausted for {url}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def fetch_json(self, url, params=None, headers=None):
        resp = self.fetch(url, params=params, headers=headers)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            logger.error(f"[{self.name}] Invalid JSON from {url}")
            return None

    @abstractmethod
    def search(self, keywords, naics_codes, set_asides):
        """Return list of opportunity dicts."""
        pass

    def _normalize_opportunity(self, **kwargs):
        """Return a standardized opportunity dict."""
        return {
            "id": kwargs.get("id", ""),
            "source": self.name,
            "title": kwargs.get("title", ""),
            "agency": kwargs.get("agency", ""),
            "office": kwargs.get("office", ""),
            "description": kwargs.get("description", ""),
            "naics_code": kwargs.get("naics_code", ""),
            "set_aside": kwargs.get("set_aside", ""),
            "type": kwargs.get("type", ""),
            "posted_date": kwargs.get("posted_date", ""),
            "response_deadline": kwargs.get("response_deadline", ""),
            "url": kwargs.get("url", ""),
            "estimated_value": kwargs.get("estimated_value", ""),
            "attachments": kwargs.get("attachments", []),
            "contact": kwargs.get("contact", ""),
            "place_of_performance": kwargs.get("place_of_performance", ""),
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
        }
