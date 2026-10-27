"""A Tempo client: search traces by attribute, which is how per-user and per-tenant questions get answered."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import requests


class TempoError(RuntimeError):
    """Tempo answered with an error or something this client cannot read."""


@dataclass(frozen=True, slots=True)
class TraceHit:
    """One search result."""

    trace_id: str
    duration_ms: float
    root_name: str


class TempoClient:
    """Tag search, TraceQL search and trace lookup."""

    def __init__(self, base_url: str, session: requests.Session | None = None) -> None:
        """Take the Tempo base URL."""
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()

    def ready(self) -> bool:
        """True when Tempo reports itself ready."""
        try:
            response = self._session.get(f"{self._base}/ready", timeout=5)
        except requests.RequestException:
            return False
        return response.status_code == 200 and "ready" in response.text

    def _search(self, params: Mapping[str, str | int]) -> list[TraceHit]:
        try:
            response = self._session.get(f"{self._base}/api/search", params=dict(params), timeout=60)
        except requests.RequestException as error:
            raise TempoError(f"search failed: {error}") from error
        if response.status_code != 200:
            raise TempoError(f"Tempo answered {response.status_code}: {response.text[:200]}")
        traces: list[dict[str, Any]] = response.json().get("traces", [])
        return [
            TraceHit(item["traceID"], float(item.get("durationMs", 0)), str(item.get("rootTraceName", "")))
            for item in traces
        ]

    def search_by_tags(self, tags: Mapping[str, str], start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces having every ``key=value`` tag, in the time range (the lesson's ``/api/search?tags=`` call)."""
        encoded = " ".join(f"{key}={value}" for key, value in tags.items())
        return self._search({"tags": encoded, "start": int(start), "end": int(end) + 1, "limit": limit})

    def search_traceql(self, query: str, start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces matching a TraceQL query in the time range."""
        return self._search({"q": query, "start": int(start), "end": int(end) + 1, "limit": limit})

    def wait_for_search(
        self, search: Callable[[], list[TraceHit]], expected_at_least: int, timeout_seconds: float = 90.0
    ) -> list[TraceHit]:
        """Poll a zero-argument ``search`` callable until it returns ``expected_at_least`` hits."""
        deadline = time.monotonic() + timeout_seconds
        hits: list[TraceHit] = []
        while time.monotonic() < deadline:
            hits = search()
            if len(hits) >= expected_at_least:
                return hits
            time.sleep(2.0)
        return hits
