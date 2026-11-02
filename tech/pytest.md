# pytest (with pytest-cov and coverage)

## What it is

pytest is a Python library and command that finds and runs **tests**. A test is a function whose name starts with `test_`. It sets up some data, calls the code being tested, and uses `assert` to state what must be true. If an `assert` is false, or any error escapes, the test is reported as failed; otherwise it passes. pytest also gives you **fixtures** (reusable setup code that tests receive by naming it as a parameter), **parametrization** (one test run with many inputs) and **markers** (labels on tests so you can run a subset).

## Why this repository uses it

The lesson says "assert the numbers". Unit tests prove the series arithmetic, the label switch and the scenario's order of phases without any container. Configuration tests lint the files as code (most importantly: the guarded Prometheus file differs from the baseline by the drop rule only). The integration and end-to-end tests run against the real stack, and the end-to-end test runs the *whole lesson* at a tenth of its size and asserts every number.

## Where it appears

| Path | What it holds |
| --- | --- |
| `tests/conftest.py` | The shared in-memory OpenTelemetry fixture. |
| `tests/unit/domain`, `application`, `infrastructure`, `interfaces`, `lab` | Unit tests, no containers. |
| `tests/observability/test_configuration_as_code.py` | Lints the compose file, the Collector, both Prometheus files, the rules, the dashboard and the placement guide. |
| `tests/integration/test_running_stack.py` | The running stack (marker `integration`). |
| `tests/e2e/test_lesson_scenario.py` | The whole scenario at a tenth of the size (marker `e2e`). |
| `pyproject.toml` | `[tool.pytest.ini_options]` and `[tool.coverage.*]`. |

## How it works underneath

`pytest` starts one process. It reads the configuration in `pyproject.toml`, walks the folders listed in `testpaths`, imports every file named `test_*.py` and collects every function named `test_*`. Before it runs a test it looks at the parameter names: for each name it finds a fixture function of that name (in the test file, or in `conftest.py` files in parent folders), runs it, and passes the result in. If a fixture uses `yield`, the code after the `yield` runs after the test, as cleanup.

pytest rewrites `assert` statements while it imports test files, so a failed `assert a == b` prints both values and where they differ.

`monkeypatch` is a built-in fixture that changes an attribute or environment variable for one test and puts it back afterwards. `caplog` captures log records. `tmp_path` is a fresh temporary folder. `pytest.raises(SomeError)` is a context manager that passes only if the block raises that error.

**Coverage** measures which lines of your code ran during the tests. `pytest-cov` plugs the `coverage` tool into pytest.

**Unit tests** test one piece without the outside world (fakes stand in for the database and network). **Integration tests** test pieces against real running services. **End-to-end tests** run the whole scenario the way a user would. This repository keeps the three kinds in three folders and uses markers so that `make test` runs only the first kind.

## Walkthrough of this repository's use

### Configuration in `pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: needs the stack from docker-compose.yml (make up)",
    "e2e: runs the whole lesson scenario at reduced scale against the stack (make up first)",
]

[tool.coverage.run]
source = ["cardinality_lab"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
```

`testpaths = ["tests"]`; `addopts = "-ra --strict-markers"` prints a summary for every non-passing test and turns unknown markers into errors; the two `markers` are declared with descriptions. `[tool.coverage.run]` measures only `cardinality_lab` and counts branches; `[tool.coverage.report]` prints the missing line numbers. `make test` fails if the domain and application layers fall under 95 percent.

### `tests/conftest.py`

```python
"""Shared fixtures: an in-memory OpenTelemetry pipeline that tests can read back."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass
class InMemoryTelemetry:
    """Providers whose spans and metrics stay in memory."""

    tracer_provider: TracerProvider
    span_exporter: InMemorySpanExporter
    meter_provider: MeterProvider
    metric_reader: InMemoryMetricReader


@pytest.fixture
def memory_telemetry() -> Iterator[InMemoryTelemetry]:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    yield InMemoryTelemetry(tracer_provider, exporter, meter_provider, reader)
    tracer_provider.shutdown()
    meter_provider.shutdown()
```

An OpenTelemetry pipeline that stays in memory so tests can read back what the code recorded: a tracer provider with an in-memory span exporter and a meter provider with an in-memory reader, bundled in a dataclass and yielded to the test; the code after `yield` shuts them down. A test uses it by naming `memory_telemetry` as a parameter. No network, no Collector.

### Domain and application

```python
import pytest

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.errors import InvalidIdentifierError
from cardinality_lab.domain.identifiers import TenantId, UserId
from cardinality_lab.domain.series import expected_series


@pytest.mark.parametrize("value", ["user-000001", "a", "x" * 64, "tenant_0007", "u.1-2"])
def test_valid_identifiers_are_accepted(value):
    assert UserId(value).value == value
    assert TenantId(value).value == value


@pytest.mark.parametrize("value", ["", " ", "x" * 65, "user 1", "user/1", 'user"1', "üser", "a\nb"])
def test_identifiers_with_odd_characters_or_length_are_rejected(value):
    with pytest.raises(InvalidIdentifierError):
        UserId(value)
    with pytest.raises(InvalidIdentifierError):
        TenantId(value)

```

`parametrize` runs a test once per value. Five valid identifiers (including the 64-character maximum) are accepted by both `UserId` and `TenantId`; eight bad ones (empty, a space, 65 characters, a space inside, a slash, a quote, a non-ASCII letter, a newline) are rejected. `"x" * 65` repeats a string.

```python
@pytest.mark.parametrize(
    ("draw", "outcome"),
    [
        (0.0, Outcome.DECLINED),
        (0.0199, Outcome.DECLINED),
        (0.02, Outcome.GATEWAY_ERROR),
        (0.0299, Outcome.GATEWAY_ERROR),
        (0.03, Outcome.APPROVED),
        (0.999, Outcome.APPROVED),
    ],
)
def test_the_outcome_policy_slices_the_unit_interval(draw, outcome):
    assert OutcomePolicy(0.02, 0.01).decide(draw) is outcome


def test_outcomes_carry_their_http_status():
    assert [outcome.status for outcome in Outcome] == [200, 402, 502]


@pytest.mark.parametrize(("declined", "error"), [(-0.1, 0.0), (0.0, 1.1), (0.6, 0.6)])
def test_the_outcome_policy_rejects_impossible_rates(declined, error):
    with pytest.raises(ValueError, match=r"rates|exceed"):
        OutcomePolicy(declined, error)
```

The outcome policy test tries draws on both sides of each boundary of the slices (0.0199 and 0.02, 0.0299 and 0.03). Outcomes carry the statuses 200, 402 and 502. Impossible rates (negative, above 1, adding to more than 1) raise `ValueError`; `match=r"rates|exceed"` is a regular expression for the message.

```python
def _request(route="checkout", tenant="tenant-0007"):
    return CheckoutRequest(UserId("user-000001"), TenantId(tenant), route)


def test_the_slow_rule_needs_both_the_route_and_the_tenant_to_match():
    rule = SlowDependencyRule("checkout", TenantId("tenant-0007"))
    assert rule.applies(_request())
    assert not rule.applies(_request(tenant="tenant-0008"))
    assert not rule.applies(_request(route="cart"))


def test_a_rule_without_a_route_or_tenant_never_applies():
    assert not SlowDependencyRule(None, TenantId("tenant-0007")).applies(_request())
    assert not SlowDependencyRule("checkout", None).applies(_request())

```

`_request` builds a request for the slow-rule tests. The rule applies only when both route and tenant match; a rule with `None` for either never applies.

```python
def test_the_baseline_series_count_is_the_product_of_the_label_cardinalities():
    estimate = expected_series({"route": 1, "method": 1, "status": 3}, finite_buckets=5)
    assert (estimate.label_combinations, estimate.counter_series) == (3, 3)
    assert estimate.histogram_series == 3 * (5 + 1 + 2)
    assert estimate.total == 27


def test_a_user_id_label_multiplies_every_series_by_the_number_of_users():
    safe = expected_series({"route": 1, "method": 1, "status": 3}, 5)
    unsafe = expected_series({"route": 1, "method": 1, "status": 3, "user_id": 50_000}, 5)
    assert unsafe.total == safe.total * 50_000


def test_no_labels_means_one_series_and_negative_counts_are_rejected():
    assert expected_series({}, 0).total == 1 + 3
    with pytest.raises(ValueError, match="negative"):
        expected_series({"route": -1}, 5)
```

The arithmetic: three combinations of `route × method × status` give 3 counter series and `3 × (5 + 1 + 2) = 24` histogram series, 27 in total; adding `user_id` with 50,000 values multiplies the total by 50,000; no labels at all is one series for the counter plus the histogram's four; negative counts raise.

```python
from contextlib import contextmanager

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import CheckoutRequest, Outcome
from cardinality_lab.domain.identifiers import TenantId, UserId

REQUEST = CheckoutRequest(UserId("user-000042"), TenantId("tenant-0007"))


class Gateway:
    def __init__(self, outcome):
        self.outcome = outcome

    def charge(self, request):
        return self.outcome


class Metrics:
    def __init__(self):
        self.records = []

    def record(self, route, method, status, user, duration_seconds):
        self.records.append((route, method, status, user.value, duration_seconds))


class Tracer:
    def __init__(self):
        self.requests, self.outcomes = [], []

    @contextmanager
    def span(self, request):
        self.requests.append(request)
        yield self

    def set_outcome(self, outcome):
        self.outcomes.append(outcome)


class Clock:
    def __init__(self):
        self.now = 10.0

    def monotonic(self):
        self.now += 0.5
        return self.now


def _run(outcome):
    metrics, tracer = Metrics(), Tracer()
    result = Checkout(Gateway(outcome), metrics, tracer, Clock()).execute(REQUEST)
    return result, metrics, tracer

```

Fakes: a gateway that returns a fixed outcome, a metrics recorder that stores tuples, a tracer that is a `@contextmanager` yielding itself, and a clock that advances 0.5 s per reading, so the measured duration is exactly 0.5. `_run` wires the use case and returns the result and the fakes.

```python
def test_an_approved_checkout_is_counted_with_its_status_and_duration_and_traced_with_the_request():
    result, metrics, tracer = _run(Outcome.APPROVED)
    assert result is Outcome.APPROVED
    assert metrics.records == [("checkout", "GET", 200, "user-000042", 0.5)]
    assert tracer.requests == [REQUEST]
    assert tracer.outcomes == [Outcome.APPROVED]


def test_declined_and_failed_checkouts_are_counted_too(caplog):
    with caplog.at_level("WARNING"):
        _, declined, _ = _run(Outcome.DECLINED)
        _, failed, _ = _run(Outcome.GATEWAY_ERROR)
    assert declined.records[0][2] == 402
    assert failed.records[0][2] == 502
    assert [record.outcome for record in caplog.records] == ["DECLINED", "GATEWAY_ERROR"]
    assert caplog.records[0].tenant == "tenant-0007"


def test_an_approved_checkout_logs_nothing(caplog):
    with caplog.at_level("INFO"):
        _run(Outcome.APPROVED)
    assert caplog.records == []
```

An approved checkout is recorded with route `checkout`, method `GET`, status 200, the user and duration 0.5, and traced with the request and the outcome. Declined and failed checkouts are counted too and write one `WARNING` each (`caplog` captures them); an approved one logs nothing.

### Infrastructure

```python
import pytest

from cardinality_lab.infrastructure.settings import AppSettings, SettingsError


def test_defaults_are_the_safe_baseline():
    settings = AppSettings.from_env({})
    assert settings.metrics_include_user_id is False
    assert settings.slow_tenant == ""
    assert (settings.port, settings.metrics_port, settings.bind_host) == (8080, 9100, "127.0.0.1")
    assert settings.seed is None


def test_the_experiment_switches_are_read():
    settings = AppSettings.from_env(
        {"METRICS_INCLUDE_USER_ID": "TRUE", "SLOW_TENANT": "tenant-0007", "SEED": "9", "SLOW_SECONDS": "3"}
    )
    assert settings.metrics_include_user_id is True
    assert (settings.slow_tenant, settings.seed, settings.slow_seconds) == ("tenant-0007", 9, 3.0)


@pytest.mark.parametrize(
    "env",
    [
        {"METRICS_INCLUDE_USER_ID": "yes"},
        {"DECLINED_RATE": "2"},
        {"APP_PORT": "http"},
        {"SLOW_SECONDS": "-1"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_invalid_values_are_rejected(env):
    with pytest.raises(SettingsError):
        AppSettings.from_env(env)
```

Defaults are the safe baseline (the switch off, no slow tenant, ports 8080 and 9100, loopback); the switches are read (`"TRUE"` is accepted); five invalid environments raise `SettingsError` (including `yes` for the flag).

```python
import io
import json
import logging

from cardinality_lab.infrastructure.logging_setup import JsonFormatter, configure_logging


def _record(message="hello", **extra):
    record = logging.LogRecord("test.logger", logging.INFO, __file__, 1, message, None, None)
    record.__dict__.update(extra)
    return record


def test_every_line_is_one_json_object_with_the_standard_fields():
    payload = json.loads(JsonFormatter("back").format(_record("order assembled", order_id=5)))
    assert payload["msg"] == "order assembled"
    assert (payload["level"], payload["service"], payload["logger"]) == ("info", "back", "test.logger")
    assert payload["order_id"] == 5
    assert "trace_id" not in payload


def test_inside_a_span_the_line_carries_the_trace_and_span_ids(memory_telemetry):
    tracer = memory_telemetry.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        payload = json.loads(JsonFormatter("back").format(_record()))
        context = span.get_span_context()
    assert payload["trace_id"] == f"{context.trace_id:032x}"
    assert payload["span_id"] == f"{context.span_id:016x}"


def test_exceptions_are_included_as_text():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()
    assert "ValueError: boom" in json.loads(JsonFormatter("back").format(record))["exception"]


def test_configure_logging_replaces_handlers_and_writes_json_to_the_stream():
    stream = io.StringIO()
    configure_logging("INFO", "front", stream)
    configure_logging("INFO", "front", stream)
    logging.getLogger("x").info("once")
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["service"] == "front"
```

Four tests of the log formatter (`python-logging.md`): every line is one JSON object with the standard fields; inside a span the line carries the trace and span ids (32 and 16 hex digits); an exception is included as text; and `configure_logging` called twice still writes each line once, to an in-memory stream (`io.StringIO`).

```python
import pytest
from prometheus_client import CollectorRegistry, disable_created_metrics, generate_latest

from cardinality_lab.domain.identifiers import UserId
from cardinality_lab.infrastructure.prometheus_metrics import LATENCY_BUCKETS, PrometheusCheckoutMetrics


@pytest.fixture(autouse=True, scope="module")
def _without_created_series():
    # The app does this once at start-up (interfaces/main.py); the flag is process-wide.
    disable_created_metrics()


def _series(registry):
    return [line for line in generate_latest(registry).decode().splitlines() if line and not line.startswith("#")]


def _drive(include_user_id, users):
    registry = CollectorRegistry()
    metrics = PrometheusCheckoutMetrics(registry, include_user_id)
    for number in range(users):
        metrics.record("checkout", "GET", 200, UserId(f"user-{number:06d}"), 0.004)
    return _series(registry)

```

`@pytest.fixture(autouse=True, scope="module")` runs for every test in the module without being requested; it calls `disable_created_metrics()` once (the setting is process-wide, as in the app). `_series` renders a registry with `generate_latest` and keeps the non-comment lines. `_drive` records requests for a number of users into a fresh registry.

```python
def test_without_the_user_label_the_series_count_does_not_depend_on_the_users():
    assert len(_drive(False, 5)) == len(_drive(False, 500))


def test_baseline_series_for_one_status_are_one_counter_plus_the_histogram_buckets_sum_and_count():
    assert len(_drive(False, 3)) == 1 + (len(LATENCY_BUCKETS) + 1 + 2)


def test_with_the_user_label_every_user_adds_a_full_set_of_series():
    per_user = 1 + (len(LATENCY_BUCKETS) + 1 + 2)
    assert len(_drive(True, 200)) == 200 * per_user


def test_the_unsafe_mode_exposes_the_user_id_label_and_the_safe_mode_does_not():
    assert any('user_id="user-000000"' in line for line in _drive(True, 1))
    assert not any("user_id" in line for line in _drive(False, 1))


def test_observations_land_in_the_matching_bucket_and_the_counter_counts_requests():
    registry = CollectorRegistry()
    metrics = PrometheusCheckoutMetrics(registry, False)
    for _ in range(3):
        metrics.record("checkout", "GET", 200, UserId("u"), 0.004)
    metrics.record("checkout", "GET", 502, UserId("u"), 3.0)
    assert registry.get_sample_value("requests_total", {"route": "checkout", "method": "GET", "status": "200"}) == 3
    assert (
        registry.get_sample_value(
            "request_latency_seconds_bucket", {"route": "checkout", "method": "GET", "status": "200", "le": "0.005"}
        )
        == 3
    )
    assert registry.get_sample_value("requests_total", {"route": "checkout", "method": "GET", "status": "502"}) == 1
```

The core of the lesson in tests: without the user label the series count is the same for 5 and 500 users; for one status it is `1 + (5 + 1 + 2) = 9`; with the label, 200 users make `200 × 9` series; the label appears only in unsafe mode; and observations land in the right bucket (three requests of 4 ms are in the `le="0.005"` bucket, and the 502 has its own series). `registry.get_sample_value(name, labels)` reads one value back.

```python
import random

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.identifiers import TenantId, UserId
from cardinality_lab.infrastructure.otel_tracing import OtelRequestTracer
from cardinality_lab.infrastructure.payment_gateway import SimulatedPaymentGateway


def _request(tenant="tenant-0007"):
    return CheckoutRequest(UserId("user-012345"), TenantId(tenant))


def test_the_checkout_span_carries_the_user_tenant_and_route(memory_telemetry):
    tracer = OtelRequestTracer(memory_telemetry.tracer_provider.get_tracer("t"))
    with tracer.span(_request()) as span:
        span.set_outcome(Outcome.APPROVED)
    (recorded,) = memory_telemetry.span_exporter.get_finished_spans()
    assert recorded.name == "checkout"
    assert recorded.attributes["user.id"] == "user-012345"
    assert recorded.attributes["tenant.id"] == "tenant-0007"
    assert recorded.attributes["route"] == "checkout"
    assert recorded.attributes["checkout.outcome"] == "approved"
    assert recorded.status.status_code.name == "UNSET"


def test_a_gateway_error_marks_the_span_as_an_error(memory_telemetry):
    tracer = OtelRequestTracer(memory_telemetry.tracer_provider.get_tracer("t"))
    with tracer.span(_request()) as span:
        span.set_outcome(Outcome.GATEWAY_ERROR)
    (recorded,) = memory_telemetry.span_exporter.get_finished_spans()
    assert recorded.status.status_code.name == "ERROR"


def _gateway(memory_telemetry, sleeps, rule, seed=1):
    return SimulatedPaymentGateway(
        OutcomePolicy(0.0, 0.0),
        rule,
        random.Random(seed),
        memory_telemetry.tracer_provider.get_tracer("t"),
        baseline_seconds=0.002,
        slow_seconds=2.0,
        sleep=sleeps.append,
    )


def test_the_gateway_is_slow_only_for_the_matching_route_and_tenant(memory_telemetry):
    sleeps: list[float] = []
    gateway = _gateway(memory_telemetry, sleeps, SlowDependencyRule("checkout", TenantId("tenant-0007")))
    gateway.charge(_request("tenant-0007"))
    gateway.charge(_request("tenant-0008"))
    assert sleeps == [2.0, 0.002]


def test_the_gateway_opens_a_payment_span_and_returns_the_policy_outcome(memory_telemetry):
    gateway = _gateway(memory_telemetry, [], SlowDependencyRule(None, None))
    assert gateway.charge(_request()) is Outcome.APPROVED
    (span,) = memory_telemetry.span_exporter.get_finished_spans()
    assert span.name == "payment.charge"
    assert span.attributes["tenant.id"] == "tenant-0007"
```

The `checkout` span carries `user.id`, `tenant.id`, `route` and the outcome and has no error status; a gateway error sets the status to ERROR. The gateway is built with `sleep=sleeps.append`: instead of waiting, it records the durations it would have waited, so the test sees `[2.0, 0.002]`: slow for the matching tenant only. It opens a `payment.charge` span with the tenant.

### Interfaces

```python
import pytest

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import Outcome
from cardinality_lab.interfaces.http_app import create_app


class StubCheckout(Checkout):
    def __init__(self, outcome=Outcome.APPROVED, error=None):
        self._outcome, self._error, self.seen = outcome, error, []

    def execute(self, request):
        self.seen.append(request)
        if self._error:
            raise self._error
        return self._outcome


HEADERS = {"X-User-Id": "user-000042", "X-Tenant-Id": "tenant-0007"}


def test_a_checkout_passes_the_user_and_tenant_headers_to_the_use_case():
    stub = StubCheckout()
    response = create_app(stub).test_client().get("/checkout", headers=HEADERS)
    assert (response.status_code, response.get_json()) == (200, {"outcome": "approved"})
    assert (stub.seen[0].user.value, stub.seen[0].tenant.value, stub.seen[0].route) == (
        "user-000042",
        "tenant-0007",
        "checkout",
    )


@pytest.mark.parametrize(("outcome", "status"), [(Outcome.DECLINED, 402), (Outcome.GATEWAY_ERROR, 502)])
def test_outcomes_become_their_http_status(outcome, status):
    response = create_app(StubCheckout(outcome)).test_client().get("/checkout", headers=HEADERS)
    assert response.status_code == status


@pytest.mark.parametrize(
    "headers", [{}, {"X-User-Id": "user-1"}, {"X-Tenant-Id": "t"}, {"X-User-Id": "bad id", "X-Tenant-Id": "t"}]
)
def test_missing_or_malformed_identifiers_are_a_bad_request_and_never_reach_the_use_case(headers):
    stub = StubCheckout()
    response = create_app(stub).test_client().get("/checkout", headers=headers)
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_identifier"
    assert stub.seen == []


def test_unexpected_failures_are_a_json_500():
    response = create_app(StubCheckout(error=RuntimeError("bug"))).test_client().get("/checkout", headers=HEADERS)
    assert (response.status_code, response.get_json()["error"]) == (500, "internal_error")


def test_unknown_routes_are_a_json_404_and_health_is_ok():
    client = create_app(StubCheckout()).test_client()
    assert client.get("/nope").get_json()["error"] == "not_found"
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_responses_inside_a_span_carry_the_trace_id(memory_telemetry):
    client = create_app(StubCheckout()).test_client()
    with memory_telemetry.tracer_provider.get_tracer("t").start_as_current_span("request") as span:
        response = client.get("/healthz")
        expected = f"{span.get_span_context().trace_id:032x}"
    assert response.headers["X-Trace-Id"] == expected
```

`StubCheckout` inherits the real use case but replaces `execute` with a scripted answer. Tests: headers reach the use case as a `UserId` and `TenantId` with the route `checkout`; outcomes become 402 and 502; four bad or missing header combinations give 400 `invalid_identifier` and never reach the use case (`stub.seen == []`); an unexpected exception is a JSON 500; unknown routes are a JSON 404 and health is OK; inside a span the response carries the trace id.

```python
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from cardinality_lab.interfaces.health_cli import main


def _server(status):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_exit_code_is_0_for_a_200_and_1_for_anything_else():
    healthy, broken = _server(200), _server(503)
    try:
        assert main(["--url", f"http://127.0.0.1:{healthy.server_address[1]}/healthz"]) == 0
        assert main(["--url", f"http://127.0.0.1:{broken.server_address[1]}/healthz"]) == 1
    finally:
        healthy.shutdown()
        broken.shutdown()


def test_exit_code_is_1_when_nothing_listens():
    assert main(["--url", "http://127.0.0.1:9/healthz", "--timeout", "0.5"]) == 1
```

A tiny server answers a chosen status; `main` returns 0 for 200, 1 for 503 and 1 when nothing listens.

### The lab

```python
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cardinality_lab.lab.load import LoadPlan, draw_requests, run_load, tenant_name, user_name


def test_names_are_zero_padded():
    assert user_name(12345) == "user-012345"
    assert tenant_name(7) == "tenant-0007"


def test_the_same_seed_draws_the_same_users_and_tenants():
    plan = LoadPlan("http://x", users=50_000, requests=2_000, seed=1)
    assert draw_requests(plan) == draw_requests(plan)
    assert draw_requests(plan) != draw_requests(LoadPlan("http://x", 50_000, 2_000, seed=2))


def test_the_draw_stays_inside_the_user_and_tenant_ranges():
    pairs = draw_requests(LoadPlan("http://x", users=50, requests=2_000, seed=3, tenants=10))
    assert {user for user, _ in pairs} <= {user_name(i) for i in range(1, 51)}
    assert {tenant for _, tenant in pairs} <= {tenant_name(i) for i in range(1, 11)}
    assert len({user for user, _ in pairs}) > 45


def test_run_load_sends_every_request_with_the_identity_headers_and_counts_statuses():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers["X-User-Id"], self.headers["X-Tenant-Id"]))
            self.send_response(402 if len(seen) % 10 == 0 else 200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        plan = LoadPlan(f"http://127.0.0.1:{server.server_address[1]}", users=20, requests=100, seed=5, concurrency=4)
        result = run_load(plan)
    finally:
        server.shutdown()
    assert result.sent == 100
    assert sorted(seen) == sorted(draw_requests(plan))
    assert result.statuses == {200: 90, 402: 10}
    assert sum(result.requests_per_user.values()) == 100
    assert result.distinct_users == len(result.requests_per_user)
    assert result.requests_per_second > 0


def test_a_dead_server_counts_as_status_zero():
    result = run_load(LoadPlan("http://127.0.0.1:9", users=2, requests=3, seed=1, concurrency=2))
    assert result.statuses == {0: 3}
```

Names are zero-padded; the same seed draws the same pairs and another seed a different list; draws stay inside the ranges (`<=` between sets means "subset"); and `run_load` against a throw-away server sends every request with both identity headers (`sorted(seen) == sorted(draw_requests(plan))`), counts statuses (every tenth answer is 402, so `{200: 90, 402: 10}`) and counts users. A dead address counts as status 0.

```python
import pytest

from cardinality_lab.lab.prometheus import PrometheusClient, PrometheusError


class Response:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        path = url.split("9090", 1)[1]
        self.calls.append((path, params))
        reply = self.routes[path]
        return reply(params) if callable(reply) else reply


def _instant(value):
    return Response(
        {
            "status": "success",
            "data": {"result": [{"value": [0, str(value)]}], "stats": {"timings": {"evalTotalTime": 0.0123}}},
        }
    )


def _client(routes):
    return PrometheusClient("http://prom:9090", Session(routes))  # type: ignore[arg-type]

```

A fake `Response` and a fake `Session` routed by path (`url.split("9090", 1)[1]` keeps the part after the port). `_instant` builds a Prometheus-shaped answer. `# type: ignore[arg-type]` marks the deliberate fake.

```python
def test_scalar_returns_the_value_or_the_default():
    client = _client({"/api/v1/query": _instant(41943040)})
    assert client.scalar("x") == 41943040
    empty = _client({"/api/v1/query": Response({"status": "success", "data": {"result": []}})})
    assert empty.scalar("x", default=-1) == -1


def test_head_series_and_memory_use_the_lesson_queries():
    session = Session({"/api/v1/query": _instant(1842)})
    client = PrometheusClient("http://prom:9090", session)  # type: ignore[arg-type]
    assert client.head_series() == 1842
    assert client.resident_memory_bytes() == 1842
    assert [call[1]["query"] for call in session.calls] == [
        "prometheus_tsdb_head_series",
        'process_resident_memory_bytes{job="prometheus"}',
    ]


def test_tsdb_status_lists_the_offender_first():
    body = {
        "status": "success",
        "data": {
            "seriesCountByMetricName": [{"name": "request_latency_seconds_bucket", "value": 350000}],
            "labelValueCountByLabelName": [{"name": "user_id", "value": 49000}, {"name": "status", "value": 3}],
        },
    }
    status = _client({"/api/v1/status/tsdb": Response(body)}).tsdb_status()
    assert status.top_label == ("user_id", 49000)
    assert status.top_metric == ("request_latency_seconds_bucket", 350000)


def test_timed_query_reports_the_engine_time_and_the_row_count():
    timing = _client({"/api/v1/query": _instant(1)}).timed_query(runs=2)
    assert timing.engine_milliseconds == pytest.approx(12.3)
    assert timing.result_rows == 1
    assert timing.wall_milliseconds >= 0


def test_errors_become_prometheus_error():
    with pytest.raises(PrometheusError, match="503"):
        _client({"/api/v1/query": Response({}, status=503)}).scalar("x")
    with pytest.raises(PrometheusError, match="failed"):
        _client({"/api/v1/query": Response({"status": "error"})}).scalar("x")


def test_wait_for_scrapes_returns_once_the_count_has_grown():
    counts = iter([10, 10, 11, 12])
    client = _client({"/api/v1/query": lambda params: _instant(next(counts))})
    client.wait_for_scrapes("checkout", scrapes=2, timeout_seconds=30)
```

`scalar` returns a value or the default; the lesson's queries are the ones sent; `tsdb_status` puts the offender first; `timed_query` reports the engine time (`pytest.approx(12.3)` compares floats with a tolerance) and the row count; errors become `PrometheusError` (`match="503"`); `wait_for_scrapes` returns once the count has grown (the fake returns the numbers 10, 10, 11, 12 from an iterator).

```python
from collections import Counter
from pathlib import Path

from cardinality_lab.lab.compose import BASE_CONFIG, GUARDED_CONFIG, Compose
from cardinality_lab.lab.load import LoadResult
from cardinality_lab.lab.prometheus import Measurement, QueryTiming, TsdbStatus
from cardinality_lab.lab.scenario import SLOW_TENANT, ScenarioPlan, ScenarioRunner, render_report
from cardinality_lab.lab.tempo import TraceHit


class FakePrometheus:
    def __init__(self):
        self.series = iter([1842, 198340, 1849, 1851])

    def wait_for_scrapes(self, job, scrapes=2, timeout_seconds=180.0):
        pass

    def measure(self, job):
        return Measurement(next(self.series), 41_943_040, QueryTiming(8.0, 5.0, 1), 70)

    def tsdb_status(self):
        return TsdbStatus((("request_latency_seconds_bucket", 350000),), (("user_id", 49000), ("status", 3)))

    def scalar(self, expression, default=0.0):
        return 0.0475


class FakeTempo:
    def __init__(self):
        self.searches = []

    def search_by_tags(self, tags, start, end, limit=1000):
        return [TraceHit(f"{i:032x}", 5.0, "GET /checkout") for i in range(3)]

    def search_traceql(self, query, start, end, limit=1000):
        return [TraceHit(f"{i:032x}", 2010.0, "GET /checkout") for i in range(5)]

    def wait_for_search(self, search, expected_at_least, timeout_seconds=90.0):
        return search()


def _fake_load(plan):
    users = Counter({"user-000007": 3, "user-000008": 1})
    tenants = Counter({SLOW_TENANT: 5, "tenant-0001": 95})
    return LoadResult(plan.requests, Counter({200: plan.requests}), users, tenants, 1000.0, 1010.0)


```

Fakes for Prometheus and Tempo; `_fake_load` returns a ready-made `LoadResult` (a hundred requests, one busy user, the slow tenant with five requests).

```python
def test_the_phases_run_in_the_lessons_order_with_the_right_settings():
    calls = []
    compose = Compose(Path("."), {}, runner=lambda command, env, cwd: calls.append((command[2:4], dict(env))))
    plan = ScenarioPlan("http://app", users=50_000, requests=40_000, slow_phase_requests=100)
    log: list[str] = []
    report = ScenarioRunner(plan, compose, FakePrometheus(), FakeTempo(), load=_fake_load, log=log.append).run()

    includes = [env["METRICS_INCLUDE_USER_ID"] for command, env in calls if command == ["up", "-d"]]
    assert includes.count("true") == 2
    assert includes[:3] == ["false", "false", "true"]
    assert [line[0] for line in log if line[:1].isdigit()] == ["1", "2", "3", "4", "5", "6"]
    configs = [env["PROMETHEUS_CONFIG"] for _, env in calls]
    assert configs[0] == BASE_CONFIG
    assert GUARDED_CONFIG in configs
    slow_envs = {env["SLOW_TENANT"] for _, env in calls if env["SLOW_TENANT"]}
    assert slow_envs == {SLOW_TENANT}

    assert report.series_growth == 198340 / 1842
    assert report.diagnosis.top_label == ("user_id", 49000)
    assert (report.probe_user, report.probe_user_requests, report.probe_user_traces) == ("user-000007", 3, 3)
    assert report.slow.traces_found == 5
    assert report.slow.expected_slow_requests == 5
    assert report.slow.shortest_slow_span_seconds == 2.01

```

The phases run in the lesson's order with the right settings: the `up -d` calls show the label off, off, then on, and on twice in all; the log lines numbered 1 to 6 appear in order; the first configuration is the baseline and the guarded one is used; the slow tenant is set only to `tenant-0007`. The report numbers match (`198340 / 1842` growth, the offender `user_id`, the probe user and its traces, five slow traces, shortest span 2.01 s).

```python
def test_the_report_prints_every_number_the_lesson_asks_for():
    compose = Compose(Path("."), {}, runner=lambda *args: None)
    plan = ScenarioPlan("http://app", users=50_000, requests=40_000, slow_phase_requests=100)
    text = render_report(
        ScenarioRunner(plan, compose, FakePrometheus(), FakeTempo(), load=_fake_load, log=lambda _: None).run()
    )
    for expected in ["baseline", "with user_id", "after the fix", "guarded", "user_id", "49000", "tenant-0007", "p95"]:
        assert expected in text
    assert "1842" in text
    assert "198340" in text


def test_compose_commands_pass_the_overrides_and_failures_carry_the_output(tmp_path):
    import pytest

    from cardinality_lab.lab.compose import ComposeError, run_command

    seen = []
    compose = Compose(
        tmp_path, {"KEEP": "1"}, runner=lambda command, env, cwd: seen.append((list(command), dict(env), cwd))
    )
    compose.reset_prometheus(GUARDED_CONFIG)
    assert [entry[0][:3] for entry in seen] == [
        ["docker", "compose", "rm"],
        ["docker", "volume", "rm"],
        ["docker", "compose", "up"],
    ]
    assert all(entry[1]["KEEP"] == "1" for entry in seen)
    assert all(entry[2] == tmp_path for entry in seen)
    with pytest.raises(ComposeError, match="boom"):
        run_command(["sh", "-c", "echo boom >&2; exit 3"], {}, tmp_path)
```

The report text contains every number the lesson asks for. The last test uses `tmp_path`, a fresh temporary folder, to check that `reset_prometheus` runs `rm`, `volume rm` and `up` in that order, passes the environment and folder to each, and that `run_command` raises `ComposeError` carrying the output of a failing command (`sh -c "echo boom >&2; exit 3"`).

### Configuration as code

```python
"""Lint the files that configure the stack: compose, the Collector, both Prometheus configs, rules and dashboard."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY = ROOT / "observability"
DATASOURCE_UIDS = {"prometheus", "tempo"}


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return dict(_yaml(ROOT / "docker-compose.yml"))

```

`copy` is imported for deep copies. `DATASOURCE_UIDS` is `{"prometheus", "tempo"}`. `ROOT` finds the repository from the test's location (two folders up).

```python
def test_every_third_party_image_is_pinned_to_a_version(compose):
    images = [service["image"] for service in compose["services"].values() if "build" not in service]
    assert len(images) >= 4
    for image in images:
        assert ":" in image
        assert not image.endswith(":latest")


def test_the_base_image_is_pinned_by_digest():
    first_line = next(line for line in (ROOT / "Dockerfile").read_text().splitlines() if line.startswith("FROM"))
    assert re.search(r"@sha256:[0-9a-f]{64}$", first_line)


def test_every_published_port_is_bound_to_loopback(compose):
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"


def test_every_variable_the_compose_file_reads_is_in_env_example():
    used = set(re.findall(r"\$\{([A-Z_]+)", (ROOT / "docker-compose.yml").read_text()))
    declared = {line.split("=", 1)[0] for line in (ROOT / ".env.example").read_text().splitlines() if "=" in line}
    assert used <= declared, sorted(used - declared)


def test_the_app_runs_as_a_non_root_user_with_a_health_check_and_prometheus_has_a_memory_cap(compose):
    assert re.search(r"^USER app$", (ROOT / "Dockerfile").read_text(), re.MULTILINE)
    assert "healthcheck" in compose["services"]["app"]
    assert compose["services"]["prometheus"]["mem_limit"] == "3g"


def test_the_composed_defaults_are_the_safe_baseline(compose):
    environment = compose["services"]["app"]["environment"]
    assert environment["METRICS_INCLUDE_USER_ID"] == "${METRICS_INCLUDE_USER_ID:-false}"
    assert environment["SLOW_TENANT"] == "${SLOW_TENANT:-}"

```

Compose rules: images pinned and not `latest`; the base image pinned by a 64-hex digest; every published port bound to `127.0.0.1`; every `${VARIABLE}` declared in `.env.example`; the `USER app` line, a health check on the app and `mem_limit == "3g"` on Prometheus; and the composed defaults are the safe baseline (the switch's default is `false`, the slow tenant's is empty).

```python
def test_the_collector_traces_pipeline_has_the_memory_limiter_first_and_batch_last():
    config = _yaml(OBSERVABILITY / "collector" / "config.yaml")
    pipeline = config["service"]["pipelines"]["traces"]
    assert pipeline["processors"][0] == "memory_limiter"
    assert pipeline["processors"][-1] == "batch"
    assert all(name in config["exporters"] for name in pipeline["exporters"])


def test_the_guarded_config_differs_from_the_baseline_only_by_the_label_drop_rule():
    base = _yaml(OBSERVABILITY / "prometheus" / "prometheus.yml")
    guarded = _yaml(OBSERVABILITY / "prometheus" / "prometheus.guarded.yml")
    stripped = copy.deepcopy(guarded)
    for job in stripped["scrape_configs"]:
        job.pop("metric_relabel_configs", None)
    assert stripped == base
    checkout = next(job for job in guarded["scrape_configs"] if job["job_name"] == "checkout")
    assert checkout["metric_relabel_configs"] == [{"action": "labeldrop", "regex": "user_id"}]
    assert not any("metric_relabel_configs" in job for job in base["scrape_configs"])


def test_both_configs_load_the_rules_and_scrape_the_app_and_prometheus_itself():
    for name in ("prometheus.yml", "prometheus.guarded.yml"):
        config = _yaml(OBSERVABILITY / "prometheus" / name)
        assert config["rule_files"] == ["/etc/prometheus/rules/*.rules.yml"]
        assert {job["job_name"] for job in config["scrape_configs"]} == {"checkout", "prometheus"}

```

The Collector's traces pipeline has `memory_limiter` first and `batch` last. The guard test: load both Prometheus files, make a deep copy of the guarded one, remove its `metric_relabel_configs`, and assert the result **equals** the baseline; then assert that the guarded checkout job has exactly the rule `labeldrop` of `user_id` and that the baseline has none. Both files load the rules and scrape `checkout` and `prometheus`.

```python
def test_every_alert_has_a_severity_a_summary_and_a_runbook():
    for path in (OBSERVABILITY / "prometheus" / "rules").glob("*.rules.yml"):
        for group in _yaml(path)["groups"]:
            for rule in group["rules"]:
                assert rule["labels"]["severity"] in {"page", "ticket"}, rule["alert"]
                assert {"summary", "runbook"} <= set(rule["annotations"]), rule["alert"]


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return dict(json.loads((OBSERVABILITY / "grafana" / "dashboards" / "cardinality-blowup.json").read_text()))


def test_dashboard_panel_ids_are_unique_and_every_target_uses_a_provisioned_datasource(dashboard):
    sources = _yaml(OBSERVABILITY / "grafana" / "provisioning" / "datasources" / "datasources.yaml")["datasources"]
    assert {source["uid"] for source in sources} == DATASOURCE_UIDS
    panels = dashboard["panels"]
    assert len({panel["id"] for panel in panels}) == len(panels)
    for panel in panels:
        assert panel["title"]
        assert panel["datasource"]["uid"] in DATASOURCE_UIDS
        assert all(target["datasource"]["uid"] in DATASOURCE_UIDS for target in panel["targets"])


def test_dashboard_shows_the_lessons_three_numbers_and_the_trace_search(dashboard):
    text = json.dumps(dashboard)
    for expected in (
        "prometheus_tsdb_head_series",
        "process_resident_memory_bytes",
        "prometheus_engine_query_duration",
        "traceql",
    ):
        assert expected in text


def test_the_placement_guide_gives_a_bounded_values_rule_and_an_example_for_each_kind():
    guide = (ROOT / "docs" / "label-placement-guide.md").read_text().lower()
    for expected in ("bounded", "metric label", "span attribute", "logs only", "route", "user.id", "stack trace"):
        assert expected in guide, expected
```

Every alert has a severity of `page` or `ticket`, a summary and a runbook; dashboard panel ids are unique and every panel and target uses a provisioned data source; the dashboard contains the lesson's metric names and a TraceQL query; and the label-placement guide (`docs/label-placement-guide.md`) contains the words that make it useful (bounded, metric label, span attribute, logs only, a route, `user.id`, stack trace).

### Integration and end-to-end

```python
"""Against the stack that `make up` started: the baseline app exposes only bounded labels and the stores answer."""

from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.tempo import TempoClient

pytestmark = pytest.mark.integration

APP = f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '28082')}"
PROMETHEUS = PrometheusClient(f"http://127.0.0.1:{os.environ.get('PROMETHEUS_HOST_PORT', '29090')}")
TEMPO = TempoClient(f"http://127.0.0.1:{os.environ.get('TEMPO_HOST_PORT', '23200')}")


def test_the_app_answers_a_checkout_and_rejects_a_request_without_identity():
    ok = requests.get(f"{APP}/checkout", headers={"X-User-Id": "user-000001", "X-Tenant-Id": "tenant-0001"}, timeout=10)
    assert ok.status_code in {200, 402, 502}
    assert len(ok.headers["X-Trace-Id"]) == 32
    assert requests.get(f"{APP}/checkout", timeout=10).status_code == 400


def test_prometheus_scrapes_the_app_and_the_series_carry_only_route_method_and_status():
    for number in range(30):
        requests.get(
            f"{APP}/checkout", headers={"X-User-Id": f"user-{number:06d}", "X-Tenant-Id": "tenant-0001"}, timeout=10
        )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and not PROMETHEUS.scalar('up{job="checkout"}'):
        time.sleep(2)
    assert PROMETHEUS.scalar('up{job="checkout"}') == 1
    series = 'count(requests_total{job="checkout",route="checkout"})'
    while time.monotonic() < deadline and not PROMETHEUS.scalar(series):
        time.sleep(2)
    # Ask for the series directly: the TSDB statistics list only the labels with the most values, and a label with
    # one value ("route") can fall outside that list on a Prometheus with many labels of its own.
    assert PROMETHEUS.scalar(series) > 0
    assert PROMETHEUS.scalar('count({job="checkout",user_id!=""})') == 0


def test_one_request_leaves_exactly_one_trace_findable_by_its_user_id():
    user = f"user-{uuid.uuid4().hex[:12]}"
    started = time.time()
    requests.get(f"{APP}/checkout", headers={"X-User-Id": user, "X-Tenant-Id": "tenant-0002"}, timeout=10)
    hits = TEMPO.wait_for_search(lambda: TEMPO.search_by_tags({"user.id": user}, started - 5, time.time() + 30), 1)
    assert len(hits) == 1
```

`pytestmark = pytest.mark.integration` labels every test. Against the running stack: the app answers a checkout (200, 402 or 502, with a 32-character trace id) and rejects a request without identity (400); after 30 requests from 30 users, Prometheus scrapes the app (`up == 1`, waiting up to 90 s) and the app's series are there with the label `route` and **no** `user_id` label at all. The test asks for the series directly (`count(requests_total{...})` and `count({job="checkout",user_id!=""}) == 0`) because Prometheus's label statistics list only the labels with the most values, and a label with one value, like `route`, can fall outside that list; and one request with a random user (`uuid.uuid4().hex[:12]`) leaves exactly one trace findable by that user id.

```python
"""The whole lesson at a tenth of its size, asserted number by number against the real stack."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cardinality_lab.lab.compose import Compose
from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.scenario import Report, ScenarioPlan, ScenarioRunner, render_report
from cardinality_lab.lab.tempo import TempoClient

pytestmark = pytest.mark.e2e

USERS = 5_000
REQUESTS = 20_000


@pytest.fixture(scope="module")
def report() -> Report:
    env = os.environ
    plan = ScenarioPlan(f"http://127.0.0.1:{env.get('APP_HOST_PORT', '28082')}", USERS, REQUESTS)
    runner = ScenarioRunner(
        plan,
        Compose(Path(__file__).resolve().parents[2], env),
        PrometheusClient(f"http://127.0.0.1:{env.get('PROMETHEUS_HOST_PORT', '29090')}"),
        TempoClient(f"http://127.0.0.1:{env.get('TEMPO_HOST_PORT', '23200')}"),
    )
    result = runner.run()
    print(render_report(result))
    return result

```

`USERS = 5_000` and `REQUESTS = 20_000` are a tenth of the lesson. A module-scoped fixture runs the whole scenario once and prints the report; every test reads the same `report`.

```python
def test_step_1_the_expected_series_count_is_computed_from_the_labels(report):
    assert report.expected.counter_series == 3
    assert report.expected.histogram_series == 3 * (5 + 1 + 2)


def test_step_2_a_user_id_label_grows_series_memory_and_samples_by_orders_of_magnitude(report):
    assert report.series_growth >= 10
    assert report.blown_up.resident_memory_bytes > report.baseline.resident_memory_bytes
    assert report.blown_up.samples_per_scrape >= 10 * report.baseline.samples_per_scrape
    assert report.blown_up.query.engine_milliseconds >= report.baseline.query.engine_milliseconds


def test_step_3_the_top_label_in_the_backends_own_statistics_is_user_id(report):
    label, values = report.diagnosis.top_label
    assert label == "user_id"
    assert values >= 0.9 * report.distinct_users
    assert report.diagnosis.top_metric[0].startswith("request_latency_seconds")


def test_step_4_the_series_count_returns_near_baseline_and_one_users_requests_are_still_findable(report):
    assert report.fixed.head_series <= 2 * report.baseline.head_series
    assert report.fixed.samples_per_scrape <= 2 * report.baseline.samples_per_scrape
    assert report.probe_user_traces == report.probe_user_requests


def test_step_4_the_guard_keeps_a_re_added_label_from_creating_series(report):
    assert report.guarded.head_series <= 2 * report.baseline.head_series
    # The guard strips the label after the scrape, so the colliding samples still count as scraped; it is the
    # stored series that stay at the baseline.
    assert report.guarded.samples_per_scrape > 10 * report.baseline.samples_per_scrape


def test_step_5_traces_find_the_slow_dependency_that_the_route_p95_hides(report):
    slow = report.slow
    assert slow.expected_slow_requests >= 20
    assert slow.traces_found >= 0.9 * slow.expected_slow_requests
    assert slow.shortest_slow_span_seconds >= 1.5
    assert slow.tenant_share < 0.01
    assert slow.route_p95_after_seconds <= max(2 * slow.route_p95_before_seconds, 0.05)
```

Step 1: the expected counter and histogram series. Step 2: the user label grows series by at least 10 times, memory goes up, samples per scrape grow at least tenfold and the query is not faster. Step 3: the top label in Prometheus's own statistics is `user_id` with at least 90 percent of the distinct users, and the top metric is a latency series. Step 4: after the fix the head series are at most twice the baseline and every request of the probe user is findable in traces; the guard keeps a re-added label from creating series (the comment explains why samples per scrape stay high: the guard strips the label *after* the scrape, so colliding samples still count as scraped, while the stored series stay at baseline). Step 5: at least 20 slow requests, at least 90 percent found by trace search, the shortest slow span at least 1.5 s, the tenant under one percent of traffic, and the route's p95 after is at most twice the p95 before (or 50 ms).

## Try it yourself

```bash
make test
```

Expected: all unit and configuration tests pass, then `Required test coverage of 95% reached`.

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_prometheus_metrics.py -v
```

Expected: five tests, each `PASSED`.

```bash
.venv/bin/python -m pytest tests/unit -k "series or user" -q
```

Expected: only the tests whose names contain those words run.

```bash
.venv/bin/python -m pytest tests/integration tests/e2e --collect-only -q | tail -3
```

Expected: the integration and end-to-end tests are listed without running.

```bash
make test-e2e
```

Expected (needs `make up`; about ten minutes): all end-to-end tests pass, after printing the scenario report once.

## Mistakes people make

- **Tests that depend on each other's order or leftovers.** Each test here builds its own data.
- **Sleeping for a fixed time** to wait for something. This repository polls with a deadline, and its unit tests replace `time.sleep` with `monkeypatch`.
- **Patching globally and forgetting to undo.** `monkeypatch` undoes itself.
- **Asserting too little.** `assert response` passes for any non-empty object. Assert the exact thing that matters.
- **Mocking everything.** A test full of mocks proves the mocks work. Fakes here are small hand-written classes with real behavior.
- **Typos in marker names.** `--strict-markers` turns an unknown marker into an error.

## Check yourself

1. What makes a function a test for pytest? *Its name starts with `test_` and it lives in a file named `test_*.py` (or in the configured paths).*
2. How does a test receive a fixture? *By naming it as a parameter.*
3. What does code after `yield` in a fixture do? *It runs after the test as cleanup.*
4. What does `pytest.raises` check? *That the block inside it raises the named exception.*
5. Why keep unit and integration tests apart? *Unit tests need no running services and run fast; integration tests need the stack.*

## Further reading

- pytest 9 documentation: https://docs.pytest.org/en/stable/
- Fixtures: https://docs.pytest.org/en/stable/how-to/fixtures.html
- Parametrize: https://docs.pytest.org/en/stable/how-to/parametrize.html
- pytest-cov: https://pytest-cov.readthedocs.io/en/latest/
- coverage.py: https://coverage.readthedocs.io/en/7.17.0/
