# requests and urllib3

## What it is

`requests` is the most widely used Python library for making HTTP calls. `requests.get(url)` sends a GET request and returns a `Response` with `.status_code`, `.headers`, `.text` and `.json()`. A **Session** keeps connections open between calls (faster) and lets you set options once. `urllib3` is the lower-level library that `requests` uses underneath, and `urllib.request` from the standard library is a simpler client that needs no installation. This repository uses requests 2.34 and urllib3 2.8.

## Why this repository uses it

Three roles. The **load generator** sends the app thousands of requests per second with the user's identity in headers. The **Prometheus client** asks Prometheus the lesson's questions (how many series, how much memory, which label is the offender). The **Tempo client** searches traces by attribute, the replacement for the per-user metric. All three are plain HTTP.

## Where it appears

| Path | What it does with requests |
| --- | --- |
| `src/cardinality_lab/lab/load.py` | One keep-alive session per worker thread (see `python-threads-and-signals.md`). |
| `src/cardinality_lab/lab/prometheus.py` | Instant queries, TSDB statistics, timed queries and waiting for scrapes. |
| `src/cardinality_lab/lab/tempo.py` | Tag search, TraceQL search and polling for results. |
| `tests/integration/test_running_stack.py` | Calls the app directly. |
| `tests/unit/lab/test_prometheus_client.py` | Tests the client with a fake session. |

## How it works underneath

A Session owns a **connection pool** per host. The first call opens a TCP connection; later calls reuse it (HTTP keep-alive). An **adapter** (`HTTPAdapter`) is mounted for a URL prefix such as `http://`, and decides how connections are made and how failures are retried. A `Retry` object from urllib3 describes the policy: `total` attempts, which status codes to retry (`status_forcelist`), which HTTP methods are safe to repeat (`allowed_methods`), `backoff_factor` (the pause grows: roughly `backoff_factor * 2^(attempt-1)` seconds), and `read=False` (do not retry when the server already received the request and the wait for its answer ran out).

`timeout=5.0` is applied to the connect step and to each wait for data. It is **not** a limit for the whole request. Without a timeout, `requests` waits forever. Failures raise exceptions that derive from `requests.RequestException`; `requests.Timeout` is the timeout one.

`response.json()` parses the body as JSON and raises `ValueError` (a `JSONDecodeError`) when the body is not JSON.

The OpenTelemetry requests instrumentation patches `Session.send`, so each outgoing call becomes a client span and the `traceparent` header is added.

## Walkthrough of this repository's use

### `lab/prometheus.py`

```python
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
```

Three constants hold the lesson's queries. `prometheus_tsdb_head_series` is the number of active series in the head block. `process_resident_memory_bytes{job="prometheus"}` is the memory Prometheus itself uses. `sum(rate(requests_total[5m])) by (route)` is the dashboard query whose cost the lesson measures (see `promql.md`).

```python
class PrometheusError(RuntimeError):
    """Prometheus answered with an error or something this client cannot read."""
```

`PrometheusError` is the one error this module raises.

```python
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
```

`TsdbStatus` holds two lists from Prometheus's own statistics endpoint, each largest first: series per metric name and distinct values per label name. `top_label` and `top_metric` return the first of each: the offender.

```python
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
```

`QueryTiming` has the wall time (measured by the client) and the engine time (measured by Prometheus) of one query, in milliseconds, plus the number of result rows. `Measurement` is the lesson's three numbers plus the per-scrape sample count; `memory_megabytes` converts bytes to megabytes by dividing by a million (`1_000_000`).

```python
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
```

The client takes the base URL and an optional `requests.Session` (a fake in tests). `ready` calls `/-/healthy` with a 5-second timeout and returns False on any network error.

```python
    def _get(self, path: str, params: Mapping[str, str] | None = None, timeout: float = 300.0) -> dict[str, Any]:
        """GET a Prometheus API path; a blown-up Prometheus can take minutes to answer, so one timeout is retried."""
        for attempt in range(2):
            try:
                response = self._session.get(f"{self._base}{path}", params=params, timeout=timeout)
                break
            except requests.Timeout as error:
                if attempt == 1:
                    raise PrometheusError(f"GET {path} timed out twice: {error}") from error
            except requests.RequestException as error:
                raise PrometheusError(f"GET {path} failed: {error}") from error
        if response.status_code != 200:
            raise PrometheusError(f"Prometheus answered {response.status_code} for {path}: {response.text[:200]}")
        body: dict[str, Any] = response.json()
        if body.get("status") != "success":
            raise PrometheusError(f"Prometheus query failed: {body}")
        return body
```

`_get` is the one place that calls the API. The docstring explains the defaults: a blown-up Prometheus can take minutes to answer, so the timeout is 300 seconds and one timeout is retried. `for attempt in range(2)` tries twice. `break` leaves the loop when a response arrives. A first `requests.Timeout` is swallowed so the loop retries; a second raises `PrometheusError("... timed out twice")`; any other `requests.RequestException` raises at once. Then it checks the HTTP status and the JSON field `"status": "success"` that Prometheus puts in every answer.

```python
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
```

`scalar` runs an instant query and returns the first result's value (`result[0]["value"][1]` is the second element of the `[timestamp, "value"]` pair) as a float, or a default when there is no result. `head_series`, `resident_memory_bytes` and `samples_per_scrape` use it. `scrape_samples_post_metric_relabeling{job="checkout"}` is the number of samples a scrape of the app produced *after* the relabeling rules ran, which is what is actually stored. The f-string doubles the braces to write literal ones.

```python
    def tsdb_status(self) -> TsdbStatus:
        """The backend's own statistics: series per metric and distinct values per label."""
        data = self._get("/api/v1/status/tsdb", {"limit": "50"})["data"]
        by_metric = tuple((item["name"], int(item["value"])) for item in data["seriesCountByMetricName"])
        by_label = tuple((item["name"], int(item["value"])) for item in data["labelValueCountByLabelName"])
        return TsdbStatus(by_metric, by_label)
```

`tsdb_status` calls `/api/v1/status/tsdb` with `limit=50`. By default that endpoint lists only the top 10 entries, and 50 makes sure the label that matters is in the answer. The two nested lists are turned into tuples of `(name, count)`.

```python
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
```

`timed_query` runs the dashboard query `runs` times (default 3) with `stats=all`, which makes Prometheus include timings. `time.perf_counter()` brackets each call to get the wall time in milliseconds; `body["data"]["stats"]["timings"]["evalTotalTime"]` is the engine's own time in seconds. It returns the **median** of each (`statistics.median`), which ignores one outlier.

```python
    def measure(self, job: str) -> Measurement:
        """Take the lesson's three measurements at this moment."""
        return Measurement(
            self.head_series(), self.resident_memory_bytes(), self.timed_query(), self.samples_per_scrape(job)
        )

    def wait_for_scrapes(self, job: str, scrapes: int = 2, timeout_seconds: float = 900.0) -> None:
        """Block until the target ``job`` has been scraped ``scrapes`` more times since this call."""
        start = self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])')
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])') >= start + scrapes:
                return
            time.sleep(2.0)
        raise PrometheusError(f"{job} was not scraped {scrapes} times within {timeout_seconds:.0f}s")
```

`measure` bundles the lesson's measurements at this moment. `wait_for_scrapes` records how many times the job has been scraped in the last hour (`count_over_time(scrape_duration_seconds{...}[1h])`), then polls every 2 seconds until the count has grown by the requested number or 900 seconds pass. This is what makes a measurement trustworthy: it waits until Prometheus has actually scraped the new traffic.

### `lab/tempo.py`

```python
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

```

`TempoError` and `TraceHit` (trace id, duration in milliseconds, name of the root span).

```python
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
```

The client and its `ready` check (`/ready` returns 200 and the word `ready`).

```python
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
```

`_search` calls `/api/search` with a 60-second timeout and turns each result into a `TraceHit`. `item.get("durationMs", 0)` supplies a default when Tempo omits a field (very short traces have no `durationMs`).

```python
    def search_by_tags(self, tags: Mapping[str, str], start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces having every ``key=value`` tag, in the time range (the lesson's ``/api/search?tags=`` call)."""
        encoded = " ".join(f"{key}={value}" for key, value in tags.items())
        return self._search({"tags": encoded, "start": int(start), "end": int(end) + 1, "limit": limit})

    def search_traceql(self, query: str, start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces matching a TraceQL query in the time range."""
        return self._search({"q": query, "start": int(start), "end": int(end) + 1, "limit": limit})
```

`search_by_tags` is the lesson's call: `/api/search?tags=user.id=user-000007` finds traces with that attribute (several tags are joined with spaces). `search_traceql` sends a TraceQL query in the `q` parameter. Both take a time range in Unix seconds (`end + 1` makes the end inclusive) and a limit.

```python
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
```

`wait_for_search` takes a function that performs the search and calls it every two seconds until it returns at least the expected number of hits or 90 seconds pass, then returns what it has. Tempo needs a few seconds to index new spans, so a search right after the traffic can find fewer than were sent.

### The load generator

`lab/load.py` uses `requests.Session()` per worker and sends the identity as headers; it is explained line by line in `python-threads-and-signals.md`.

## Try it yourself

```bash
.venv/bin/python -m pytest tests/unit/lab/test_prometheus_client.py -q
```

Expected: `6 passed`.

```bash
.venv/bin/python -c "
from cardinality_lab.lab.prometheus import PrometheusClient
client = PrometheusClient('http://127.0.0.1:29090')
print(client.head_series(), client.tsdb_status().top_label)"
```

Expected (needs `make up`): the baseline number of series (a few hundred, for example 669) and the label with the most values, for example `('__name__', 292)`.

```bash
curl -s "http://127.0.0.1:29090/api/v1/status/tsdb?limit=3" | python3 -m json.tool | head -20
```

Expected: the beginning of the statistics JSON with `headStats` and `seriesCountByMetricName`.

```bash
curl -s -H "X-User-Id: user-000009" -H "X-Tenant-Id: tenant-0001" -o /dev/null http://127.0.0.1:28082/checkout; sleep 10; curl -s --get "http://127.0.0.1:23200/api/search" --data-urlencode "tags=user.id=user-000009" | python3 -m json.tool | head
```

Expected: one trace in `traces`: the request is findable by its user id.

```bash
.venv/bin/python -c "
from cardinality_lab.lab.tempo import TempoClient
print(TempoClient('http://127.0.0.1:23200').ready())"
```

Expected: `True`.

## Mistakes people make

- **No timeout.** The most common cause of a hung service.
- **Retrying a read timeout.** The slow server is already busy; a retry doubles the work. `read=False` avoids it.
- **Creating a new Session per call**, losing connection reuse.
- **Catching `Exception` instead of `requests.RequestException`.**
- **Not checking `status_code` before `.json()`.**

## Check yourself

1. What does a Session add over `requests.get`? *Connection reuse and shared settings.*
2. What does `timeout=5.0` limit? *The connect wait and each wait for data, not the total time.*
3. Which exception means "took too long"? *`requests.Timeout`.*
4. Why is only `GET` retried here? *It is idempotent: repeating it changes nothing.*
5. What does `raise_on_status=False` change? *After the retries are used up, the last response is returned instead of an exception.*

## Further reading

- requests 2.34 documentation: https://requests.readthedocs.io/en/stable/
- Advanced usage (sessions, adapters, timeouts): https://requests.readthedocs.io/en/stable/user/advanced/
- urllib3 `Retry`: https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry
- `urllib.request`: https://docs.python.org/3.12/library/urllib.request.html
