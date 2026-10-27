"""A Prometheus client for the measurements the lesson asks for."""

from __future__ import annotations

import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests

SERIES_COUNT_QUERY = "prometheus_tsdb_head_series"
MEMORY_QUERY = 'process_resident_memory_bytes{job="prometheus"}'
DASHBOARD_QUERY = "sum(rate(requests_total[5m])) by (route)"


class PrometheusError(RuntimeError):
    """Prometheus answered with an error or something this client cannot read."""


@dataclass(frozen=True, slots=True)
class TsdbStatus:
    """The head statistics from ``/api/v1/status/tsdb``, largest first."""

    series_by_metric: tuple[tuple[str, int], ...]
    values_by_label: tuple[tuple[str, int], ...]

    @property
    def top_label(self) -> tuple[str, int]:
        """The label name with the most distinct values."""
        return self.values_by_label[0]

    @property
    def top_metric(self) -> tuple[str, int]:
        """The metric name with the most series."""
        return self.series_by_metric[0]


@dataclass(frozen=True, slots=True)
class QueryTiming:
    """How long one dashboard query takes, measured two ways."""

    wall_milliseconds: float
    engine_milliseconds: float
    result_rows: int


@dataclass(frozen=True, slots=True)
class Measurement:
    """The three numbers the lesson records at each step, plus the per-scrape sample count."""

    head_series: int
    resident_memory_bytes: int
    query: QueryTiming
    samples_per_scrape: int

    @property
    def memory_megabytes(self) -> float:
        """Resident memory in MB."""
        return self.resident_memory_bytes / 1_000_000


class PrometheusClient:
    """Instant queries, timed queries and TSDB statistics."""

    def __init__(self, base_url: str, session: requests.Session | None = None) -> None:
        """Take the Prometheus base URL."""
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()

    def ready(self) -> bool:
        """True when Prometheus reports itself healthy."""
        try:
            return self._session.get(f"{self._base}/-/healthy", timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def _get(self, path: str, params: Mapping[str, str] | None = None, timeout: float = 120.0) -> dict[str, Any]:
        try:
            response = self._session.get(f"{self._base}{path}", params=params, timeout=timeout)
        except requests.RequestException as error:
            raise PrometheusError(f"GET {path} failed: {error}") from error
        if response.status_code != 200:
            raise PrometheusError(f"Prometheus answered {response.status_code} for {path}: {response.text[:200]}")
        body: dict[str, Any] = response.json()
        if body.get("status") != "success":
            raise PrometheusError(f"Prometheus query failed: {body}")
        return body

    def scalar(self, expression: str, default: float = 0.0) -> float:
        """Run an instant query expected to return at most one series and return its value."""
        result = self._get("/api/v1/query", {"query": expression})["data"]["result"]
        return float(result[0]["value"][1]) if result else default

    def head_series(self) -> int:
        """``prometheus_tsdb_head_series``: active series in the head block."""
        return int(self.scalar(SERIES_COUNT_QUERY))

    def resident_memory_bytes(self) -> int:
        """Prometheus's own resident memory."""
        return int(self.scalar(MEMORY_QUERY))

    def samples_per_scrape(self, job: str) -> int:
        """Samples the last scrape of ``job`` returned after relabeling."""
        return int(self.scalar(f'scrape_samples_post_metric_relabeling{{job="{job}"}}'))

    def tsdb_status(self) -> TsdbStatus:
        """The backend's own statistics: series per metric and distinct values per label."""
        data = self._get("/api/v1/status/tsdb", {"limit": "50"})["data"]
        by_metric = tuple((item["name"], int(item["value"])) for item in data["seriesCountByMetricName"])
        by_label = tuple((item["name"], int(item["value"])) for item in data["labelValueCountByLabelName"])
        return TsdbStatus(by_metric, by_label)

    def timed_query(self, expression: str = DASHBOARD_QUERY, runs: int = 3) -> QueryTiming:
        """Run the dashboard query ``runs`` times and return the median wall time and engine time."""
        walls: list[float] = []
        engines: list[float] = []
        rows = 0
        for _ in range(runs):
            started = time.perf_counter()
            body = self._get("/api/v1/query", {"query": expression, "stats": "all"})
            walls.append((time.perf_counter() - started) * 1000)
            engines.append(float(body["data"]["stats"]["timings"]["evalTotalTime"]) * 1000)
            rows = len(body["data"]["result"])
        return QueryTiming(statistics.median(walls), statistics.median(engines), rows)

    def measure(self, job: str) -> Measurement:
        """Take the lesson's three measurements at this moment."""
        return Measurement(
            self.head_series(), self.resident_memory_bytes(), self.timed_query(), self.samples_per_scrape(job)
        )

    def wait_for_scrapes(self, job: str, scrapes: int = 2, timeout_seconds: float = 180.0) -> None:
        """Block until the target ``job`` has been scraped ``scrapes`` more times since this call."""
        start = self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])')
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])') >= start + scrapes:
                return
            time.sleep(2.0)
        raise PrometheusError(f"{job} was not scraped {scrapes} times within {timeout_seconds:.0f}s")
