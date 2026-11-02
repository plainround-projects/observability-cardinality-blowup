# OpenTelemetry (Python API, SDK, exporter and instrumentation)

## What it is

OpenTelemetry (OTel) is an open standard, plus libraries for many languages, for producing **telemetry**: the three kinds of evidence a running program can give about itself.

- A **trace** records the path of one request through the system. It is a tree of **spans**. A span is one timed step with a name, a start time, an end time, a parent span, and **attributes** (key/value notes such as `db.statement`). All spans of one request share one **trace id**.
- A **metric** is a number measured over time: a counter that only goes up, a gauge that moves up and down, or a **histogram** that counts how many measurements fell into each range ("bucket") of values.
- A **log** is a line of text (here JSON) with a time and a level. When written inside a span, a log line can carry that span's trace id and span id, which is what links the three signals.

OpenTelemetry does not store or display anything. It defines how to *produce* and *send* the data (the **OTLP** protocol, the OpenTelemetry Protocol, over HTTP or gRPC) so that any backend can receive it.

## Why this repository uses it

The lesson's fix is "move the per-user detail from the metric to the trace". A trace span can carry `user.id` as an **attribute** without any cost to Prometheus, because Tempo stores each span once and searches it on demand. So this repository uses OpenTelemetry for **traces only**: the Flask instrumentation makes a server span per request, and the code adds a `checkout` span and a `payment.charge` span with the identifiers on them. Metrics do not use OpenTelemetry here (`OTEL_METRICS_EXPORTER: none`); they go straight from `prometheus_client` to Prometheus, which is what makes the mistake easy to demonstrate and the guard (in Prometheus) necessary.

## Where it appears

| Path | What it does with OpenTelemetry |
| --- | --- |
| `src/cardinality_lab/infrastructure/otel_tracing.py` | The `checkout` span with `user.id`, `tenant.id`, `route` and the outcome. |
| `src/cardinality_lab/infrastructure/payment_gateway.py` | The `payment.charge` span around the (simulated) downstream call. |
| `src/cardinality_lab/infrastructure/logging_setup.py`, `interfaces/http_app.py` | Read the current span for the trace id (see `python-logging.md`, `flask.md`). |
| `src/cardinality_lab/interfaces/main.py` | Gets the tracer from the API. |
| `Dockerfile`, `docker-compose.yml` | Start the app through `opentelemetry-instrument` and set the `OTEL_*` variables. |
| `pyproject.toml` | Lists the distro, the OTLP/HTTP exporter and the Flask instrumentation. |
| `tests/conftest.py`, `tests/unit/infrastructure/test_tracing_and_gateway.py` | An in-memory pipeline that tests read back. |

## How it works underneath

The Python packages are split by role:

- `opentelemetry-api` holds the names your code calls (`trace.get_tracer`, `metrics.get_meter`). With no SDK configured the calls do nothing, so libraries can use the API safely.
- `opentelemetry-sdk` is the real implementation: it makes spans, aggregates metrics, batches them and hands them to **exporters**.
- `opentelemetry-exporter-otlp-proto-http` is the exporter that sends OTLP over HTTP (protobuf-encoded) to a Collector.
- `opentelemetry-instrumentation-*` packages wrap a library (Flask, requests, psycopg) so that every request, outgoing call or SQL statement creates a span automatically. This is **auto-instrumentation**.
- `opentelemetry-distro` and `opentelemetry-instrument` are the glue: the command `opentelemetry-instrument <program>` sets up the SDK from environment variables (`OTEL_*`), switches on all installed instrumentations, and then runs the program. The program's own code needs no setup lines.

**Context propagation.** The current span is stored in a *context* (a `contextvars` variable) so code deeper in the call chain automatically becomes a child. When `requests` calls another service, the requests instrumentation adds the `traceparent` header, and the Flask instrumentation on the other side reads it and continues the same trace.

**Resource.** A set of attributes that describe the process producing the data (`service.name=back`). The backends use `service.name` to tell the services apart.

**Exemplars.** When a measurement is recorded inside a span, the SDK can attach the trace id and span id of that span to the histogram sample. Prometheus then stores "this sample (1.5 s) came from trace X". A dashboard turns it into a dot you can click to open the trace.

**Logs.** Python's standard `logging` module is bridged: a `LoggingHandler` converts each record into an OTLP log record, including the active trace id and span id.

Data leaves the process in batches on a timer, so a request is not visible in the backends for a few seconds.

## Walkthrough of this repository's use

### `infrastructure/otel_tracing.py`: where the user id lives

```python
"""The OpenTelemetry adapter: where the user id lives, as a span attribute, one value per trace."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span, Status, StatusCode, Tracer

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome

SPAN_NAME = "checkout"
```

Only the OpenTelemetry **API** is imported (`Span`, `Status`, `StatusCode`, `Tracer`), never the SDK. `contextmanager` turns a generator function into something usable in a `with`. The span is named `checkout`.

```python
class _OtelRequestSpan:
    def __init__(self, span: Span) -> None:
        self._span = span

    def set_outcome(self, outcome: Outcome) -> None:
        self._span.set_attribute("checkout.outcome", outcome.name.lower())
        self._span.set_attribute("http.response.status_code", outcome.status)
        if outcome is Outcome.GATEWAY_ERROR:
            self._span.set_status(Status(StatusCode.ERROR, "gateway error"))
```

`_OtelRequestSpan` is the object the use case receives. `set_outcome` records two **attributes** on the span: `checkout.outcome` (`approved`, `declined` or `gateway_error`) and `http.response.status_code`. Attributes are key/value notes attached to a span; Tempo can search on them. For a gateway error it also sets the span **status** to ERROR with a description, so error traces stand out; a declined card is a business outcome and leaves the status unset.

```python
class OtelRequestTracer:
    """Opens the ``checkout`` span, a child of the HTTP server span, with the request's identifiers on it."""

    def __init__(self, tracer: Tracer) -> None:
        """Take the tracer to create spans with."""
        self._tracer = tracer

    @contextmanager
    def span(self, request: CheckoutRequest) -> Iterator[_OtelRequestSpan]:
        """Open the span with ``user.id``, ``tenant.id`` and ``route``."""
        with self._tracer.start_as_current_span(SPAN_NAME) as span:
            span.set_attribute("user.id", request.user.value)
            span.set_attribute("tenant.id", request.tenant.value)
            span.set_attribute("route", request.route)
            yield _OtelRequestSpan(span)
```

`OtelRequestTracer.span` is a `@contextmanager`. `self._tracer.start_as_current_span(SPAN_NAME)` starts the span and makes it the current one, so it becomes a **child of the HTTP server span** that the Flask instrumentation opened, and anything created inside (the payment span, the log lines) becomes its descendant. The three `set_attribute` lines put `user.id`, `tenant.id` and `route` on the span: *this* is where the unbounded user id belongs. `yield` hands the wrapper to the use case; when the `with` block ends, the span ends.

### `infrastructure/payment_gateway.py`: a second span

```python
"""A simulated payment gateway: fast for everyone, slow for one route and one tenant."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from opentelemetry.trace import Tracer

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule

```

The simulated gateway takes the outcome policy, the slow rule, a random generator, a tracer, the two delays and an injectable `sleep` (so tests do not really wait).

```python
class SimulatedPaymentGateway:
    """Waits a baseline time, or ``slow_seconds`` when the slow-dependency rule applies, then decides the outcome."""

    def __init__(
        self,
        policy: OutcomePolicy,
        rule: SlowDependencyRule,
        rng: random.Random,
        tracer: Tracer,
        baseline_seconds: float,
        slow_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Take the outcome policy, the slow rule, the random generator, a tracer and the two delays."""
        self._policy = policy
        self._rule = rule
        self._rng = rng
        self._tracer = tracer
        self._baseline_seconds = baseline_seconds
        self._slow_seconds = slow_seconds
        self._sleep = sleep
```

The class docstring says what it does: wait a baseline time, or `slow_seconds` when the rule applies, then decide the outcome.

```python
    def charge(self, request: CheckoutRequest) -> Outcome:
        """Call the 'downstream' inside its own span and return the outcome."""
        slow = self._rule.applies(request)
        with self._tracer.start_as_current_span("payment.charge") as span:
            span.set_attribute("peer.service", "payment-gateway")
            span.set_attribute("tenant.id", request.tenant.value)
            self._sleep(self._slow_seconds if slow else self._baseline_seconds)
            return self._policy.decide(self._rng.random())
```

`charge` first asks the rule whether this request is the slow one. It then opens a span `payment.charge` with the attributes `peer.service = payment-gateway` and `tenant.id`, sleeps for the slow or baseline time **inside** the span, and returns the policy's decision for a random draw. So the trace of a slow request has a visibly wide `payment.charge` span, and the attribute `tenant.id` is how the lesson finds them.

### How the rest is configured

The Dockerfile's `CMD` and the Compose `command` start the app as `opentelemetry-instrument cardinality-lab-app`. The environment in `docker-compose.yml` configures the SDK:

```yaml
      OTEL_SERVICE_NAME: checkout
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318
      OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
      OTEL_TRACES_EXPORTER: otlp
      OTEL_METRICS_EXPORTER: none
      OTEL_LOGS_EXPORTER: none
      OTEL_PYTHON_FLASK_EXCLUDED_URLS: healthz
```

- `OTEL_SERVICE_NAME: checkout` becomes the resource attribute `service.name`.
- `OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318` is the Collector, by its Compose service name, on its OTLP/HTTP port; `OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf` selects OTLP over HTTP with Protocol Buffers.
- `OTEL_TRACES_EXPORTER: otlp` switches trace export on; `OTEL_METRICS_EXPORTER: none` and `OTEL_LOGS_EXPORTER: none` switch the other two off.
- `OTEL_PYTHON_FLASK_EXCLUDED_URLS: healthz` is a comma-separated list of regular expressions of URLs that must not be traced, so the health checks (every ten seconds) do not fill Tempo.

## Try it yourself

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_tracing_and_gateway.py -q
```

Expected: `4 passed`.

```bash
curl -s -D - -o /dev/null -H "X-User-Id: user-000123" -H "X-Tenant-Id: tenant-0003" http://127.0.0.1:28082/checkout | grep -i x-trace-id
```

Expected (needs `make up`): `X-Trace-Id: ` plus 32 hex characters.

```bash
sleep 8; curl -s --get "http://127.0.0.1:23200/api/search" --data-urlencode 'tags=user.id=user-000123' | python3 -m json.tool | head -20
```

Expected: one trace whose `rootServiceName` is `checkout`.

```bash
curl -s --get "http://127.0.0.1:23200/api/search" --data-urlencode 'q={ span.tenant.id = "tenant-0003" }' --data-urlencode 'limit=3' | python3 -m json.tool | head -12
```

Expected: traces of that tenant (the span attribute `tenant.id` is written `span.tenant.id` in TraceQL).

```bash
docker compose exec app env | grep ^OTEL_ | sort
```

Expected: the variables listed above.

## Mistakes people make

- **Using unbounded values as metric labels** (user ids, order ids). Every distinct value is a new time series. This repository puts only a four-value bucket on the metric and the order id on spans and logs, where unlimited values are fine.
- **Recording a measurement outside the span** and then wondering why the exemplar is missing. Exemplars need a span active at the moment of recording.
- **Forgetting that the SDK buffers.** A short-lived process must flush on exit.
- **Mixing up the API and the SDK.** Application code should only import the API.
- **Missing propagation.** If a client library is not instrumented, the trace breaks into two.

## Check yourself

1. What are the three signals? *Traces, metrics and logs.*
2. What is a span? *One timed step in a request, with a parent, attributes and a trace id shared with the rest of the request.*
3. What does `opentelemetry-instrument` do? *It configures the SDK from `OTEL_*` variables, enables the installed instrumentations and runs your program.*
4. How does the trace continue from the front service to the back service? *The `requests` instrumentation sends a `traceparent` header and the Flask instrumentation reads it.*
5. What is an exemplar? *A trace id attached to one histogram sample, so you can open the trace that produced it.*

## Further reading

- OpenTelemetry concepts: https://opentelemetry.io/docs/concepts/
- Python instrumentation (SDK 1.45, instrumentations 0.66b1): https://opentelemetry.io/docs/languages/python/
- Zero-code Python: https://opentelemetry.io/docs/zero-code/python/
- OTLP specification: https://opentelemetry.io/docs/specs/otlp/
- Environment variables: https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/
