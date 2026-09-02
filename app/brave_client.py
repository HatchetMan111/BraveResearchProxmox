"""Dünner Client für die Brave Search API (Web- und News-Endpoint).

Reihenfolge bei jeder Anfrage: 1) Cache prüfen (kostet nichts) ->
2) Budget prüfen (BudgetExceededError falls voll) -> 3) HTTP-Request ->
4) Ergebnis cachen + Budget verbuchen.

Wird das Budget während eines Laufs mit mehreren Queries erschöpft, bricht
NUR diese eine Query ab (BudgetExceededError propagiert nach oben); die
Pipeline entscheidet, ob sie mit bereits vorliegenden Ergebnissen weitermacht.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from .budget_tracker import BudgetTracker
from .cache import ResponseCache

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    age: str | None = None  # z.B. "2 days ago" -- nur bei News-Suche gesetzt
    raw: dict[str, Any] = field(default_factory=dict)


class BraveClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        budget_tracker: BudgetTracker,
        cache: ResponseCache,
        session: requests.Session | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.budget = budget_tracker
        self.cache = cache
        self.session = session or requests.Session()

    def web_search(self, query: str, count: int = 10) -> list[SearchResult]:
        return self._search("/web/search", query, count)

    def news_search(self, query: str, count: int = 10) -> list[SearchResult]:
        return self._search("/news/search", query, count)

    def _search(self, endpoint: str, query: str, count: int) -> list[SearchResult]:
        cache_key = self.cache.make_key(endpoint, query, count=count)
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("Cache-Treffer für %r (%s) -- 0 Requests verbraucht", query, endpoint)
            return [SearchResult(**item) for item in cached]

        # Wirft BudgetExceededError, falls kein Kontingent mehr frei ist.
        self.budget.record_request(1)

        resp = self.session.get(
            f"{self.base_url}{endpoint}",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
            params={"q": query, "count": count},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        results = [self._parse_result(item) for item in self._extract_items(endpoint, data)]

        self.cache.set(
            cache_key,
            query,
            [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "age": r.age,
                    "raw": {},  # Rohdaten nicht cachen, um die DB klein zu halten
                }
                for r in results
            ],
        )
        return results

    @staticmethod
    def _extract_items(endpoint: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        if endpoint == "/news/search":
            return data.get("results", [])
        return data.get("web", {}).get("results", [])

    @staticmethod
    def _parse_result(item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("description", ""),
            age=item.get("age"),
            raw=item,
        )
