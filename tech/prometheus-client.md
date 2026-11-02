# prometheus_client (Python library, 0.26)

## What it is

`prometheus_client` is the official Python library for **exposing metrics in the Prometheus format**. You create metric objects (a `Counter`, a `Gauge`, a `Histogram`), update them from your code, and the library serves their current values as text at `/metrics` on a port of your choosing. Prometheus then scrapes that page (see `prometheus.md`). The library does not store history; it only keeps the current totals in memory.

Words you need:

- A **registry** (`CollectorRegistry`) is the collection of metrics that one `/metrics` page shows. The library has a default global one, `REGISTRY`.
- A **label** is a name/value pair that splits one metric into several **series**: `requests_total{route="checkout", status="200"}` and `requests_total{route="checkout", status="502"}` are two series. You declare the label *names* when you create the metric, and give *values* each time you update it with `.labels(...)`.
- A **Counter** only goes up. In the exposition format its name gets the suffix `_total`. A **Histogram** counts observations into buckets whose upper edges you choose.

## Why this repository uses it

The lesson's mistake is a **metric label** with too many values. To make that mistake honestly, the app uses the same library most Python services use and exposes the result directly to Prometheus. (The metrics do not go through OpenTelemetry or the Collector here: `OTEL_METRICS_EXPORTER` is `none`.) A single switch decides whether the metrics carry the extra label `user_id`.

## Where it appears

| Path | What it does with the library |
| --- | --- |
| `src/cardinality_lab/infrastructure/prometheus_metrics.py` | The counter, the histogram and the switchable mistake. |
| `src/cardinality_lab/interfaces/main.py` | Starts the `/metrics` page on its own port and turns off `_created` series. |
| `tests/unit/infrastructure/test_prometheus_metrics.py` | Counts the series the library would expose. |
| `observability/prometheus/prometheus.yml` | Scrapes `app:9100`, where the page is served. |

## How it works underneath

`start_http_server(9100, addr=host)` starts a small HTTP server in a **background thread** of the same process. Each request to `/metrics` makes the library walk the registry and write one line per series: the name, the labels in braces, a space and the value. Lines starting with `#` are `HELP` and `TYPE` comments.

A histogram with buckets `(0.005, 0.01, 0.05, 0.5, 2.5)` and labels `route`, `method`, `status` exposes, **for every combination of label values**: one `_bucket` line for each of the five finite buckets, one for `le="+Inf"`, one `_sum` and one `_count`: eight series. A counter adds one series per combination. So the number of series is the number of label combinations times the series per metric. A `user_id` label with 50,000 values multiplies that by 50,000: this is the arithmetic in `domain/series.py`.

By default, each counter and histogram also exposes a `<name>_created` series holding the creation time. They double the series count and carry no information here; `disable_created_metrics()` turns them off for the whole process.

The library keeps one child object in memory for each distinct label combination, forever. With 50,000 users the app itself holds hundreds of thousands of objects and writes tens of megabytes on every scrape: the app is also a victim of the mistake, not only Prometheus.

## Walkthrough of this repository's use

```python
"""The Prometheus adapter: a request counter and a latency histogram with a deliberate, switchable mistake."""

from __future__ import annotations

from collections.abc import Sequence

from prometheus_client import CollectorRegistry, Counter, Histogram

from cardinality_lab.domain.identifiers import UserId

# Few buckets on purpose: every bucket is one more series per label combination, which is what the lab measures.
LATENCY_BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.05, 0.5, 2.5)
SAFE_LABELS: tuple[str, ...] = ("route", "method", "status")
UNSAFE_LABELS: tuple[str, ...] = (*SAFE_LABELS, "user_id")
```

`Counter`, `Histogram` and `CollectorRegistry` are the library's classes. `LATENCY_BUCKETS` has only five finite edges on purpose (5 ms, 10 ms, 50 ms, 500 ms, 2.5 s); the comment says why: every bucket is one more series per label combination, which is what the lab measures. `SAFE_LABELS` are the three bounded labels and `UNSAFE_LABELS` adds `user_id` with the unpacking syntax `(*SAFE_LABELS, "user_id")`, which puts the items of the first tuple in the new one.

```python
class PrometheusCheckoutMetrics:
    """``requests_total`` and ``request_latency_seconds``, labeled by route, method and status.

    With ``include_user_id`` the metrics also carry a ``user_id`` label. That is the lesson's mistake, kept behind a
    switch so the scenario can make it, measure it and undo it without editing code.
    """

    def __init__(
        self,
        registry: CollectorRegistry,
        include_user_id: bool,
        buckets: Sequence[float] = LATENCY_BUCKETS,
    ) -> None:
        """Register the two metrics in ``registry``."""
        self._include_user_id = include_user_id
        labels = UNSAFE_LABELS if include_user_id else SAFE_LABELS
        self._requests = Counter("requests", "Requests handled.", labels, registry=registry)
        self._latency = Histogram(
            "request_latency_seconds", "Request latency.", labels, buckets=tuple(buckets), registry=registry
        )
```

The constructor takes the registry, the switch and the buckets. The docstring says the user label "is the lesson's mistake, kept behind a switch". `Counter("requests", "Requests handled.", labels, registry=registry)` creates a counter named `requests` (the library appends `_total` when exposing), with a help text and the label names; `Histogram("request_latency_seconds", ..., buckets=...)` the same for latency. The name `request_latency_seconds` ends with its unit, a convention.

```python
    def record(self, route: str, method: str, status: int, user: UserId, duration_seconds: float) -> None:
        """Count the request and observe its latency."""
        values = {"route": route, "method": method, "status": str(status)}
        if self._include_user_id:
            values["user_id"] = user.value
        self._requests.labels(**values).inc()
        self._latency.labels(**values).observe(duration_seconds)
```

`record` builds the label values as a dict. Prometheus labels are strings, so the status is written `str(status)`. When the switch is on, `user_id` is added. `self._requests.labels(**values).inc()` finds (or creates) the child for that combination and adds one; `**values` unpacks the dict into keyword arguments. `.observe(duration_seconds)` puts the duration into the right bucket and adds to `_sum` and `_count`.

```python
"""Composition root: read settings, build the adapters, expose /metrics on its own port, serve."""

from __future__ import annotations

import os
import random
import time

from opentelemetry import trace
from prometheus_client import REGISTRY, disable_created_metrics, start_http_server

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.identifiers import TenantId
from cardinality_lab.infrastructure.logging_setup import configure_logging
from cardinality_lab.infrastructure.otel_tracing import OtelRequestTracer
from cardinality_lab.infrastructure.payment_gateway import SimulatedPaymentGateway
from cardinality_lab.infrastructure.prometheus_metrics import PrometheusCheckoutMetrics
from cardinality_lab.infrastructure.settings import AppSettings
from cardinality_lab.interfaces.http_app import create_app
from cardinality_lab.interfaces.server import run_server


class _MonotonicClock:
    def monotonic(self) -> float:
        return time.monotonic()

```

The imports include `REGISTRY` (the default registry), `disable_created_metrics` and `start_http_server`. `_MonotonicClock` is the real clock behind the `Clock` protocol.

```python
def main() -> None:
    """Start the checkout app."""
    settings = AppSettings.from_env(os.environ)
    configure_logging(settings.log_level, settings.service_name)
    # The `_created` series double the count of every counter and histogram and carry no information here.
    disable_created_metrics()
    metrics = PrometheusCheckoutMetrics(REGISTRY, settings.metrics_include_user_id)
    tracer = trace.get_tracer("cardinality_lab")
```

`main` reads the settings and configures logging. `disable_created_metrics()` removes the `_created` series (the comment explains: they double the count). Then it builds the metrics adapter on the default registry with the switch from the settings, and gets a tracer from the OpenTelemetry API.

```python
    rule = SlowDependencyRule(
        settings.slow_route or None, TenantId(settings.slow_tenant) if settings.slow_tenant else None
    )
    gateway = SimulatedPaymentGateway(
        OutcomePolicy(settings.declined_rate, settings.error_rate),
        rule,
        random.Random(settings.seed),
        tracer,
        settings.baseline_gateway_seconds,
        settings.slow_seconds,
    )
    checkout = Checkout(gateway, metrics, OtelRequestTracer(tracer), _MonotonicClock())
    start_http_server(settings.metrics_port, addr=settings.bind_host)
    run_server(create_app(checkout), settings.bind_host, settings.port)
```

It builds the slow-dependency rule (`settings.slow_route or None`, and a `TenantId` only if a tenant is set), the gateway with a seeded random generator, and the use case. `start_http_server(settings.metrics_port, addr=settings.bind_host)` serves `/metrics` on port 9100 in a background thread. `run_server(...)` serves the checkout app on 8080 in the main thread. Two ports: one for the application, one for the metrics page that Prometheus scrapes.

## Try it yourself

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_prometheus_metrics.py -q
```

Expected: `5 passed`.

```bash
.venv/bin/python -c "
from prometheus_client import CollectorRegistry, disable_created_metrics, generate_latest
from cardinality_lab.domain.identifiers import UserId
from cardinality_lab.infrastructure.prometheus_metrics import PrometheusCheckoutMetrics
disable_created_metrics()
r = CollectorRegistry()
m = PrometheusCheckoutMetrics(r, False)
m.record('checkout', 'GET', 200, UserId('u1'), 0.004)
print(generate_latest(r).decode())"
```

Expected: a `requests_total{...} 1.0` line and nine more lines for the latency histogram: five buckets, `+Inf`, `_sum` and `_count`.

```bash
docker compose exec prometheus wget -q -O - http://app:9100/metrics | grep -c '^request_latency_seconds'
```

Expected (needs `make up`, after some traffic): 8 series for each status seen (24 for three statuses).

```bash
docker compose exec prometheus wget -q -O - http://app:9100/metrics | grep requests_total | head -3
```

Expected: `requests_total{method="GET",route="checkout",status="200"} ...`, with no `user_id` label.

```bash
METRICS_INCLUDE_USER_ID=true docker compose up -d --force-recreate --no-deps --wait app && make load USERS=300 REQUESTS=600 && docker compose exec prometheus wget -q -O - http://app:9100/metrics | grep -c 'user_id='; docker compose up -d --force-recreate --no-deps --wait app
```

Expected: a count in the thousands (several hundred users times eight series plus the counters), then the last command restores the safe baseline. This is the mistake in miniature.

## Mistakes people make

- **A label whose values come from users, ids, URLs or error messages.** Every distinct value is a new series, held in memory forever. Put such detail in a trace attribute or a log.
- **Too many histogram buckets** multiplied by many label combinations.
- **Using the default global registry in tests.** Metrics registered twice raise an error; tests here create a fresh `CollectorRegistry`.
- **Forgetting that `/metrics` is served by a thread** in the same process.
- **Leaving `_created` series on** when they are not needed.

## Check yourself

1. Does `prometheus_client` store history? *No. It keeps current totals; Prometheus stores the history by scraping.*
2. How many series does a histogram with five finite buckets make per label combination? *Eight: five buckets, `+Inf`, `_sum` and `_count`.*
3. What does `.labels(**values).inc()` do? *Finds or creates the series for that label combination and adds one.*
4. Why is `user_id` dangerous as a label? *Every user adds a full set of series, and the number of users is unbounded.*
5. What does `start_http_server` do? *Serves `/metrics` from a background thread on the given port.*

## Further reading

- prometheus_client for Python (0.26): https://prometheus.github.io/client_python/
- Counter: https://prometheus.github.io/client_python/instrumenting/counter/
- Histogram: https://prometheus.github.io/client_python/instrumenting/histogram/
- Labels: https://prometheus.github.io/client_python/instrumenting/labels/
- Exposition format: https://prometheus.io/docs/instrumenting/exposition_formats/
- Label best practices: https://prometheus.io/docs/practices/naming/#labels
