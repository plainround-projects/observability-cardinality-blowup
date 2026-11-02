# Python

## What it is

Python is a programming language. A programming language is a way to write instructions that a computer follows. You write the instructions in plain text files that end in `.py`. A program called the **interpreter** reads those files and carries out the instructions one at a time. You do not have to translate them into machine code first.

Python is popular for services, scripts and tests because its code is short and readable. This repository uses Python 3.12 inside the container images and Python 3.12 or 3.13 on your own machine. The text `from __future__ import annotations` at the top of most files and the `str | None` style of writing types both need Python 3.10 or newer; `StrEnum` needs 3.11; `datetime.UTC` needs 3.11.

Some words you will meet again and again in these notes:

- A **module** is one `.py` file. A **package** is a folder of modules that has an `__init__.py` file in it. Here, `three_signals` is the package and `three_signals/domain/orders.py` is the module `three_signals.domain.orders`.
- A **function** is a named block of instructions. A **class** is a blueprint for objects that keep some data and have functions (called **methods**) that work on that data.
- A **type hint** (also called an annotation) is a note such as `order_id: int` that says what kind of value is expected. Python itself ignores type hints when the program runs. Tools such as `mypy` read them and warn you about mistakes before you run anything.
- A **standard library** module comes with Python itself (for example `json`, `logging`, `time`, `random`). A **third-party** package is installed from outside (for example Flask or requests).

## Why this repository uses it

The lesson is about what happens inside Prometheus when a metric label has too many values, so the app that produces the metrics, the load that exercises it, and the script that measures the damage are all Python. The code is layered so that the *decision* about which fields become metric labels lives in one small adapter (`prometheus_metrics.py`), the user's identity goes to traces in another (`otel_tracing.py`), and the business rules (`domain`) and the use case (`application`) know about neither.

## Where it appears

| Path | What it does with Python |
| --- | --- |
| `src/cardinality_lab/domain/` | Identifiers, outcomes, the slow-dependency rule and the arithmetic of time series. No outside libraries. |
| `src/cardinality_lab/application/` | The `Checkout` use case and the `Protocol`s it needs. |
| `src/cardinality_lab/infrastructure/` | Adapters: settings, Prometheus metrics, OpenTelemetry spans, the simulated gateway, logging, shutdown. |
| `src/cardinality_lab/interfaces/` | The Flask app, the process entry point, the health probe. |
| `src/cardinality_lab/lab/` | The experiment: load generator, store clients, Docker control and the six-phase scenario. |
| `tests/` | pytest tests (see `pytest.md`). |

## How it works underneath

When you run `python something.py`, the operating system starts one **process**. A process is one running program with its own memory. The interpreter inside that process reads your file, turns it into a simpler internal form called **bytecode**, and runs the bytecode.

When one module says `import json`, the interpreter looks for a module with that name. It looks in the folders listed in `sys.path`. The first time a module is imported, its top-level lines run once, and the result is remembered. Importing the same module again is cheap because the remembered copy is reused.

Python is **dynamically typed**. A variable has no fixed type; the value it points to has one. That is why type hints and `mypy` exist: they add the checking that the language itself does not do.

Python has a **global interpreter lock** (the GIL). In the standard build only one thread runs Python bytecode at a time. Threads still help when the program mostly waits for the network or a database, because a waiting thread lets another thread run. All the services in these repositories spend most of their time waiting, so threads are enough.

A **virtual environment** (a `.venv` folder) is a private copy of the interpreter's package folder. You install the project's dependencies into it, so they do not mix with other projects on the same machine.

## Python features you will meet in this repository

Read this list once. Each feature is explained again, with an example from the code, where it first appears.

- **f-strings.** `f"order {order_id} does not exist"` builds a string by putting the value of the names inside the braces into the text. The `f` before the opening quote turns it on.
- **Type hints.** `def next_delay_seconds(self) -> float:` says the function returns a float. `int | None` means "an int, or None". `list[str]` is a list of strings. `tuple[OrderItem, ...]` is a tuple of any length whose items are all `OrderItem`.
- **`from __future__ import annotations`.** It tells Python to treat all type hints as text and not evaluate them when the module loads. This lets a class name itself in a hint and keeps imports used only for hints cheap.
- **Dataclasses.** `@dataclass(frozen=True, slots=True)` turns a class that only lists fields into one that has a constructor, an equality test and a readable text form generated for it. `frozen=True` forbids changing a field after creation, so the object is a fixed value. `slots=True` stores fields in a compact fixed layout instead of a dictionary.
- **Enums.** `class ItemCountBucket(StrEnum)` defines a small closed set of named values. A `StrEnum` member is also a string, so `str(ItemCountBucket.ONE_TO_TWO)` is `"1-2"`.
- **Protocols.** `class OrderRepository(Protocol)` describes what methods an object must have, without forcing it to inherit from anything. Any class with those methods fits. This is called structural typing.
- **Context managers.** `with something as name:` runs setup code on entering and cleanup code on leaving, even when an error happens. A class can offer this with `__enter__` and `__exit__`; a function can offer it with the `@contextmanager` decorator and a `yield`.
- **Decorators.** A line such as `@app.get("/healthz")` above a function hands that function to another function, which registers it or wraps it.
- **Exceptions.** `raise SomeError("text")` stops the current function and travels up the call chain until an `except SomeError:` catches it. `raise NewError(...) from error` keeps the original error attached as the cause.
- **Comprehensions.** `[x * 2 for x in numbers if x > 0]` builds a list from another sequence in one line. `{...}` with `for` builds a set or a dictionary. `( ... for ...)` inside a function call builds values lazily one at a time.
- **Keyword arguments and `**`.** `f(a=1, b=2)` passes by name. `{**one, **two}` merges two dictionaries into a new one; later keys win.
- **Closures.** A function defined inside another function can use the outer function's variables. Flask route functions in this repository are defined that way inside `create_*_app`.
- **Properties.** `@property` lets a method be read like a field: `order.total_cents` with no parentheses.
- **Class methods.** `@classmethod` gives a method that receives the class (`cls`) instead of one object. It is used here as an alternative constructor: `BackSettings.from_env(os.environ)`.
- **The `if __name__ == "__main__":` guard.** The code under it runs only when the file is started directly, not when another module imports it.

## Walkthrough of this repository's use

### The package markers

`src/cardinality_lab/__init__.py`:

```python
"""A checkout app whose metrics are overloaded with a user_id label on purpose, then fixed."""
```
`src/cardinality_lab/domain/__init__.py`:

```python
"""Identifiers, outcomes, the series arithmetic and the slow-dependency rule; depends on nothing else here."""
```
`src/cardinality_lab/application/__init__.py`:

```python
"""The checkout use case and the ports it needs; depends on the domain only."""
```
`src/cardinality_lab/infrastructure/__init__.py`:

```python
"""Adapters for Prometheus, OpenTelemetry, the simulated gateway and the process environment."""
```
`src/cardinality_lab/interfaces/__init__.py`:

```python
"""HTTP entry point and process wiring; may depend on every other layer, nothing depends on it."""
```
```python
"""The experiment: load generator, store clients and the scenario that overloads Prometheus and fixes it.

The app never imports this package; it only drives the running stack from outside.
```

Each `__init__.py` turns its folder into a package and holds a docstring that says what the layer is for and what it may depend on. The first one states the whole project in a sentence: a checkout app whose metrics are overloaded with a `user_id` label on purpose, then fixed.

### `domain/errors.py`

```python
"""Named errors that cross layer boundaries."""


class DomainError(Exception):
    """Base class for every error this project raises on purpose."""


class InvalidIdentifierError(DomainError):
    """A user or tenant id is empty, too long or contains characters outside the allowed set."""
```

`DomainError` is the base for every error raised on purpose. `InvalidIdentifierError` inherits from it and means a user or tenant id has the wrong length or characters. A class that only has a docstring needs no other body.

### `domain/identifiers.py`: validated at the boundary

```python
"""User and tenant identifiers: validated at the boundary so a client can never inject an odd value."""

from __future__ import annotations

import re
from dataclasses import dataclass

from cardinality_lab.domain.errors import InvalidIdentifierError

_ALLOWED = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _validate(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _ALLOWED.fullmatch(value):
        raise InvalidIdentifierError(f"{kind} must be 1 to 64 letters, digits, dots, dashes or underscores")
    return value
```

`re` is the standard regular-expression module. `re.compile(r"^[A-Za-z0-9_.-]{1,64}$")` builds a pattern once: `^` and `$` anchor it to the start and end of the text, the brackets list the allowed characters (letters, digits, underscore, dot, dash), and `{1,64}` means between one and sixty-four of them. The `r` before the quotes makes it a **raw string**, where backslashes are not special. `_validate` returns the value when `fullmatch` (the pattern must match the entire string) succeeds, and raises `InvalidIdentifierError` otherwise. `isinstance(value, str)` rejects non-strings first. The effect: a client cannot inject newlines, quotes, spaces or very long strings into logs, trace attributes or metric labels.

```python
@dataclass(frozen=True, slots=True)
class UserId:
    """One of the (up to 50,000) simulated users; unbounded by nature, so never a metric label."""

    value: str

    def __post_init__(self) -> None:
        """Reject values outside the allowed character set."""
        _validate("user id", self.value)


@dataclass(frozen=True, slots=True)
class TenantId:
    """One of the tenants the shop serves."""

    value: str

    def __post_init__(self) -> None:
        """Reject values outside the allowed character set."""
        _validate("tenant id", self.value)
```

`UserId` and `TenantId` are frozen dataclasses with one field and a `__post_init__` that validates it. The docstring of `UserId` states the lesson's point: a user id is *unbounded by nature*, so it must never be a metric label.

### `domain/checkout.py`: requests, outcomes and the slow rule

```python
"""A checkout request, its possible outcomes and the rule that makes one dependency slow for one slice of traffic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cardinality_lab.domain.identifiers import TenantId, UserId

ROUTE = "checkout"
METHOD = "GET"
```

`Enum` is the base class for a closed set of named constants. `ROUTE = "checkout"` and `METHOD = "GET"` are constants shared by the use case and the metrics.

```python
@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    """Who is checking out, for which tenant, on which route."""

    user: UserId
    tenant: TenantId
    route: str = ROUTE
```

`CheckoutRequest` bundles who (`user`), for which tenant, and on which `route`; `route: str = ROUTE` gives the last field a **default value**.

```python
class Outcome(Enum):
    """What a checkout ends in; the value is the HTTP status the app answers with."""

    APPROVED = 200
    DECLINED = 402
    GATEWAY_ERROR = 502

    @property
    def status(self) -> int:
        """The HTTP status code of this outcome."""
        return int(self.value)
```

`Outcome` has three members whose values are the HTTP status codes: approved 200, declined 402 (Payment Required), gateway error 502 (Bad Gateway). `status` is a property returning the value as an `int`.

```python
@dataclass(frozen=True, slots=True)
class OutcomePolicy:
    """Maps a uniform draw in [0, 1) to an outcome: first ``declined_rate`` declines, next ``error_rate`` fail."""

    declined_rate: float
    error_rate: float

    def __post_init__(self) -> None:
        """Both rates must be proportions and must not add up to more than 1."""
        if not (0.0 <= self.declined_rate <= 1.0 and 0.0 <= self.error_rate <= 1.0):
            raise ValueError("rates must be between 0 and 1")
        if self.declined_rate + self.error_rate > 1.0:
            raise ValueError("declined_rate + error_rate must not exceed 1")

    def decide(self, draw: float) -> Outcome:
        """Return the outcome for a draw."""
        if draw < self.declined_rate:
            return Outcome.DECLINED
        if draw < self.declined_rate + self.error_rate:
            return Outcome.GATEWAY_ERROR
        return Outcome.APPROVED
```

`OutcomePolicy` turns a random draw between 0 and 1 into an outcome by cutting the interval into slices: the first `declined_rate` of it is "declined", the next `error_rate` is "gateway error", the rest is "approved". `__post_init__` checks the rates are proportions and do not add to more than 1. `not (a and b)` negates a combined condition. Because the policy is a pure function of the draw, a test can try the edge values (0.0, 0.0199, 0.02, ...) without randomness.

```python
@dataclass(frozen=True, slots=True)
class SlowDependencyRule:
    """The downstream call is slow only for one route AND one tenant; ``None`` for either disables the rule."""

    route: str | None
    tenant: TenantId | None

    def applies(self, request: CheckoutRequest) -> bool:
        """True when both the route and the tenant match."""
        return (
            self.route is not None
            and self.tenant is not None
            and request.route == self.route
            and request.tenant == self.tenant
        )
```

`SlowDependencyRule` says when the downstream call is slow: only for one route **and** one tenant, and `None` for either turns the rule off. `route: str | None` is the type "a string or nothing". The condition has four parts joined by `and`; they are written one per line inside parentheses, which Python allows for a long expression.

### `domain/series.py`: the arithmetic of series

```python
"""The arithmetic of time series: how many a metric creates, worked out on paper before querying anything."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import prod


@dataclass(frozen=True, slots=True)
class SeriesEstimate:
    """Series a counter and a histogram create for a set of label cardinalities."""

    label_combinations: int
    counter_series: int
    histogram_series: int

    @property
    def total(self) -> int:
        """Counter plus histogram series."""
        return self.counter_series + self.histogram_series
```

`prod` multiplies all the numbers in a sequence (the product). `SeriesEstimate` records how many series a counter and a histogram create for a set of label cardinalities; `total` adds them.

```python
def expected_series(label_value_counts: Mapping[str, int], finite_buckets: int) -> SeriesEstimate:
    """Series for one counter and one histogram labeled by the given labels.

    Every distinct combination of label values is its own series. A histogram adds, per combination, one series per
    finite bucket, one for the ``+Inf`` bucket, one ``_sum`` and one ``_count``.
    """
    if finite_buckets < 0 or any(count < 0 for count in label_value_counts.values()):
        raise ValueError("counts must not be negative")
    combinations = prod(label_value_counts.values()) if label_value_counts else 1
    return SeriesEstimate(combinations, combinations, combinations * (finite_buckets + 1 + 2))
```

`expected_series` is the lesson's first step done on paper. A **time series** is one metric name plus one exact combination of label values. If a metric has labels with 1, 1 and 3 possible values, there are `1 × 1 × 3 = 3` combinations, so a counter makes 3 series. A histogram makes more per combination: one per finite bucket, one for the `+Inf` bucket, one `_sum` and one `_count`, i.e. `finite_buckets + 1 + 2`. With five finite buckets that is 8, so the histogram makes 24 series and the pair makes 27. Adding a label with 50,000 values multiplies everything by 50,000. `any(count < 0 for count in ...)` is true if any value is negative; negative counts are rejected with `ValueError`. `prod(...) if label_value_counts else 1` treats "no labels at all" as one series.

### `application/ports.py`

```python
"""The boundaries the use case talks through; infrastructure supplies the implementations."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome
from cardinality_lab.domain.identifiers import UserId


class CheckoutMetrics(Protocol):
    """Counts requests and times them."""

    def record(self, route: str, method: str, status: int, user: UserId, duration_seconds: float) -> None:
        """Record one finished request. The adapter decides which of these become labels."""
        ...


class RequestSpan(Protocol):
    """The span of one checkout, where the high-cardinality detail belongs."""

    def set_outcome(self, outcome: Outcome) -> None:
        """Record how the checkout ended."""
        ...


class RequestTracer(Protocol):
    """Opens the span for a checkout and attaches the request's identifiers to it."""

    def span(self, request: CheckoutRequest) -> AbstractContextManager[RequestSpan]:
        """Open a span carrying ``user.id``, ``tenant.id`` and ``route``."""
        ...


class PaymentGateway(Protocol):
    """The downstream call; slow for one route and one tenant when the fault is on."""

    def charge(self, request: CheckoutRequest) -> Outcome:
        """Charge the customer and say how it ended."""
        ...


class Clock(Protocol):
    """A monotonic clock, injected so tests control time."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary fixed point."""
        ...
```

Five protocols describe what the use case needs. `CheckoutMetrics.record(route, method, status, user, duration_seconds)` receives *everything* about the request, including the user; the docstring says "the adapter decides which of these become labels". That is the key design point: the use case always hands over the user, and the adapter, behind a switch, decides whether it becomes a label. `RequestSpan` and `RequestTracer` describe the span of one checkout (where the identifiers belong); `PaymentGateway.charge` is the downstream call; `Clock.monotonic` is an injected clock.

### `application/checkout.py`

```python
"""The checkout use case: call the payment gateway inside a span, then count and time the request."""

from __future__ import annotations

import logging

from cardinality_lab.application.ports import CheckoutMetrics, Clock, PaymentGateway, RequestTracer
from cardinality_lab.domain.checkout import METHOD, CheckoutRequest, Outcome

_log = logging.getLogger(__name__)


class Checkout:
    """Runs one checkout."""

    def __init__(
        self,
        gateway: PaymentGateway,
        metrics: CheckoutMetrics,
        tracer: RequestTracer,
        clock: Clock,
    ) -> None:
        """Wire the use case to its collaborators."""
        self._gateway = gateway
        self._metrics = metrics
        self._tracer = tracer
        self._clock = clock

    def execute(self, request: CheckoutRequest) -> Outcome:
        """Charge the customer and return the outcome; the request is counted whatever the outcome."""
        started = self._clock.monotonic()
        with self._tracer.span(request) as span:
            outcome = self._gateway.charge(request)
            span.set_outcome(outcome)
            duration = self._clock.monotonic() - started
            self._metrics.record(request.route, METHOD, outcome.status, request.user, duration)
        if outcome is not Outcome.APPROVED:
            _log.warning("checkout not approved", extra={"outcome": outcome.name, "tenant": request.tenant.value})
        return outcome
```

The constructor stores the four collaborators. `execute` reads the start time from the injected clock, opens the span with `with self._tracer.span(request) as span:`, charges the customer, stores the outcome on the span, computes the duration and records the metrics, all inside the span. After the block, anything but an approved checkout writes a `WARNING` log line with the outcome name and the tenant (`extra={...}`), so approved requests log nothing. `outcome is not Outcome.APPROVED` compares identity with the enum member. The method returns the outcome whatever it was, so the web layer can turn it into a status code.

### `infrastructure/settings.py`

```python
"""Configuration read once from the environment and validated (twelve-factor)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class SettingsError(ValueError):
    """An environment variable is missing or has an unusable value."""


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name)
    try:
        value = float(raw) if raw not in (None, "") else default
    except ValueError as error:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from error
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}, got {value}")
    return value
```

`SettingsError` and `_number` (read a number with a default and bounds) work as in any twelve-factor configuration: the environment is read once at start, converted, range-checked, and a bad value stops the process with a clear message.

```python
def _flag(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "false").strip().lower()
    if raw not in {"true", "false"}:
        raise SettingsError(f"{name} must be true or false, got {raw!r}")
    return raw == "true"
```

`_flag` reads a true/false variable. `env.get(name, "false")` defaults to `"false"`; `.strip().lower()` ignores spaces and case, so `TRUE` works; anything other than `true` or `false` (for example `yes`) is an error. Being strict here matters: the whole experiment hinges on this switch, and a misspelled value silently meaning "off" would be a nasty surprise.

```python
@dataclass(frozen=True, slots=True)
class AppSettings:
    """Everything the checkout app reads from its environment."""

    service_name: str
    bind_host: str
    port: int
    metrics_port: int
    metrics_include_user_id: bool
    declined_rate: float
    error_rate: float
    seed: int | None
    baseline_gateway_seconds: float
    slow_route: str
    slow_tenant: str
    slow_seconds: float
    log_level: str
```

`AppSettings` lists everything the app reads: the service name, the bind address and the two ports (the app's, 8080, and the metrics page, 9100), the switch `metrics_include_user_id`, the two outcome rates, an optional random `seed`, the gateway's baseline delay, and the slow route, tenant and delay.

```python
    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AppSettings:
        """Build the settings, raising ``SettingsError`` for an invalid variable."""
        level = env.get("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise SettingsError(f"LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {level!r}")
        seed = env.get("SEED", "")
        return cls(
            service_name=env.get("OTEL_SERVICE_NAME", "checkout"),
            bind_host=env.get("BIND_HOST", "127.0.0.1"),
            port=int(_number(env, "APP_PORT", 8080, 1, 65535)),
            metrics_port=int(_number(env, "METRICS_PORT", 9100, 1, 65535)),
            metrics_include_user_id=_flag(env, "METRICS_INCLUDE_USER_ID"),
            declined_rate=_number(env, "DECLINED_RATE", 0.02, 0.0, 1.0),
            error_rate=_number(env, "GATEWAY_ERROR_RATE", 0.01, 0.0, 1.0),
            seed=int(seed) if seed else None,
            baseline_gateway_seconds=_number(env, "BASELINE_GATEWAY_SECONDS", 0.002, 0.0, 5.0),
            slow_route=env.get("SLOW_ROUTE", "checkout"),
            slow_tenant=env.get("SLOW_TENANT", ""),
            slow_seconds=_number(env, "SLOW_SECONDS", 2.0, 0.0, 30.0),
            log_level=level,
        )
```

`from_env` checks the log level, then builds the object. Defaults: `declined_rate` 0.02 and `error_rate` 0.01 (so 97 percent approved), a baseline gateway time of 2 ms, `slow_route` `checkout`, `slow_tenant` empty (rule off) and `slow_seconds` 2.0. `int(_number(env, "APP_PORT", 8080, 1, 65535))` reads a number and converts it to an integer.

### `lab/scenario.py`: the six phases as code

The scenario is the lesson in one repeatable run. It is a class that receives its collaborators, so tests need no Docker.

```python
"""The lesson's six steps as one repeatable run: baseline, blow-up, diagnosis, fix, guard, hidden slow dependency."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cardinality_lab.domain.series import SeriesEstimate, expected_series
from cardinality_lab.infrastructure.prometheus_metrics import LATENCY_BUCKETS
from cardinality_lab.lab.compose import BASE_CONFIG, GUARDED_CONFIG, Compose
from cardinality_lab.lab.load import LoadPlan, LoadResult, run_load, tenant_name, user_name
from cardinality_lab.lab.prometheus import Measurement, TsdbStatus
from cardinality_lab.lab.tempo import TraceHit

JOB = "checkout"
SLOW_TENANT = tenant_name(7)
STATUS_VALUES = 3
P95_SLOW_FLOOR_SECONDS = 2.0
```

The imports show the layering: `lab` may import `domain` and `infrastructure` (here only a constant, `LATENCY_BUCKETS`) but nothing imports `lab`. Constants: the Prometheus job name, the slow tenant (`tenant-0007`), the three status values the baseline has, and a floor for the p95.

```python
class MetricsStore(Protocol):
    """The Prometheus calls the scenario makes."""

    def wait_for_scrapes(self, job: str, scrapes: int = ..., timeout_seconds: float = ...) -> None:
        """Block until the job has been scraped again."""
        ...

    def measure(self, job: str) -> Measurement:
        """The lesson's three numbers now."""
        ...

    def tsdb_status(self) -> TsdbStatus:
        """The backend's own statistics."""
        ...

    def scalar(self, expression: str, default: float = ...) -> float:
        """One value of an instant query."""
        ...


class TraceStore(Protocol):
    """The Tempo calls the scenario makes."""

    def search_by_tags(self, tags: Mapping[str, str], start: float, end: float, limit: int = ...) -> list[TraceHit]:
        """Traces with every tag."""
        ...

    def search_traceql(self, query: str, start: float, end: float, limit: int = ...) -> list[TraceHit]:
        """Traces matching a TraceQL query."""
        ...

    def wait_for_search(
        self, search: Callable[[], list[TraceHit]], expected_at_least: int, timeout_seconds: float = ...
    ) -> list[TraceHit]:
        """Poll until the search returns enough hits."""
        ...
```

Two protocols, `MetricsStore` and `TraceStore`, list only the methods of the Prometheus and Tempo clients that the scenario calls. A fake in a test satisfies them without inheriting from anything.

```python
@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    """How big to run the experiment."""

    app_url: str
    users: int
    requests: int
    seed: int = 2026
    warmup_requests: int = 5_000
    slow_phase_requests: int = 8_000


@dataclass(frozen=True, slots=True)
class SlowFinding:
    """What the hidden slow dependency looked like in metrics and in traces."""

    route_p95_before_seconds: float
    route_p95_after_seconds: float
    tenant_share: float
    traces_found: int
    shortest_slow_span_seconds: float
    expected_slow_requests: int

```

`ScenarioPlan` is the size of the experiment (the lesson's 50,000 users and 200,000 requests by default), with a warm-up of 5,000 requests and 8,000 requests for the slow-dependency phase. `SlowFinding` holds the numbers of the last phase.

```python
@dataclass(frozen=True, slots=True)
class Report:
    """Every number the lesson asks for, from one run."""

    plan: ScenarioPlan
    expected: SeriesEstimate
    baseline: Measurement
    blown_up: Measurement
    distinct_users: int
    diagnosis: TsdbStatus
    fixed: Measurement
    probe_user: str
    probe_user_requests: int
    probe_user_traces: int
    guarded: Measurement
    slow: SlowFinding

    @property
    def series_growth(self) -> float:
        """How many times more series the blow-up created."""
        return self.blown_up.head_series / max(self.baseline.head_series, 1)

```

`Report` collects every number the lesson asks for. `series_growth` is the blown-up series count divided by the baseline (`max(..., 1)` avoids dividing by zero).

```python
class ScenarioRunner:
    """Runs the phases in order against the stack, using injected collaborators."""

    def __init__(
        self,
        plan: ScenarioPlan,
        compose: Compose,
        prometheus: MetricsStore,
        tempo: TraceStore,
        load: Callable[[LoadPlan], LoadResult] = run_load,
        log: Callable[[str], None] = lambda message: print(message, flush=True),
    ) -> None:
        """Take the plan and the collaborators."""
        self._plan = plan
        self._compose = compose
        self._prometheus = prometheus
        self._tempo = tempo
        self._load = load
        self._log = log

    def _traffic(self, requests: int, seed_offset: int) -> LoadResult:
        plan = self._plan
        result = self._load(LoadPlan(plan.app_url, plan.users, requests, plan.seed + seed_offset))
        self._log(
            f"  sent {result.sent} requests from {result.distinct_users} users at {result.requests_per_second:.0f}/s"
        )
        return result

    def _settle(self) -> None:
        self._prometheus.wait_for_scrapes(JOB, scrapes=2)
```

The runner stores the plan and collaborators; the default `log` is a lambda that prints and flushes (so progress shows at once in a terminal). `_traffic` runs the load with a seed offset (each phase uses different but repeatable ids) and logs a one-line summary. `_settle` waits for two more scrapes of the app so the numbers measured next include the new traffic.

```python
    def run(self) -> Report:
        """Run every phase and return the report."""
        plan = self._plan
        self._log("1. Baseline: fresh Prometheus, three bounded labels")
        self._compose.reset_prometheus(BASE_CONFIG)
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=BASE_CONFIG)
        self._traffic(plan.warmup_requests, 0)
        self._settle()
        baseline = self._prometheus.measure(JOB)
        expected = expected_series(
            {"route": 1, "method": 1, "status": STATUS_VALUES}, finite_buckets=len(LATENCY_BUCKETS)
        )

```

Phase 1, **baseline**: reset Prometheus to an empty database with the base configuration, start the app with the safe labels, send 5,000 requests, wait for scrapes and measure. `expected_series` computes the series count on paper for one route, one method and three statuses with five buckets.

```python
        self._log("2. Blow it up: add the user_id label to both metrics and send the full traffic")
        self._compose.recreate_app(include_user_id=True, slow_tenant="", prometheus_config=BASE_CONFIG)
        blast = self._traffic(plan.requests, 1)
        self._settle()
        blown_up = self._prometheus.measure(JOB)
```

Phase 2, **blow-up**: restart the app with `include_user_id=True` and send the full traffic. Every distinct user now creates a complete set of series.

```python
        self._log("3. Find the offender from Prometheus's own statistics")
        diagnosis = self._prometheus.tsdb_status()
```

Phase 3, **diagnosis**: ask Prometheus for its own statistics (`/api/v1/status/tsdb`) and read which label has the most values and which metric the most series.

```python
        self._log("4. Fix: remove the label, keep user.id on the span, start from a fresh Prometheus with the guard")
        self._compose.reset_prometheus(GUARDED_CONFIG)
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        fix_load = self._traffic(plan.requests // 4, 2)
        self._settle()
        fixed = self._prometheus.measure(JOB)
        probe_user, probe_requests = fix_load.requests_per_user.most_common(1)[0]
        hits = self._tempo.wait_for_search(
            lambda: self._tempo.search_by_tags(
                {"user.id": probe_user}, fix_load.started_at - 5, fix_load.finished_at + 30
            ),
            expected_at_least=probe_requests,
        )
```

Phase 4, **fix**: a fresh Prometheus with the guarded configuration, the app without the label, a quarter of the traffic. The busiest user (`most_common(1)[0]` of a `Counter`) becomes the probe: the scenario asks Tempo for all traces with that `user.id` and expects one per request, proving the detail was not lost, only moved from metrics to traces.

```python
        self._log("5. Guard: someone adds user_id back; the scrape rule drops it before storage")
        self._compose.recreate_app(include_user_id=True, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        self._traffic(plan.requests // 4, 3)
        self._settle()
        guarded = self._prometheus.measure(JOB)
```

Phase 5, **guard**: the mistake is repeated (the label is back) but the guarded configuration drops it before storage; the series count must stay near the baseline.

```python
        self._log("6. Hidden slow dependency: one route, one tenant, found from traces")
        slow = self._slow_dependency()
        return Report(
            plan=plan,
            expected=expected,
            baseline=baseline,
            blown_up=blown_up,
            distinct_users=blast.distinct_users,
            diagnosis=diagnosis,
            fixed=fixed,
            probe_user=probe_user,
            probe_user_requests=probe_requests,
            probe_user_traces=len(hits),
            guarded=guarded,
            slow=slow,
        )
```

Phase 6 is `_slow_dependency`; then the report is built from everything measured.

```python
    def _route_p95(self, window_seconds: float) -> float:
        expression = (
            "histogram_quantile(0.95, sum by (le) "
            f'(increase(request_latency_seconds_bucket{{job="{JOB}"}}[{int(window_seconds)}s])))'
        )
        return self._prometheus.scalar(expression)
```

`_route_p95` computes the 95th percentile of the whole route over a window with `histogram_quantile` over `increase(...)` of the buckets (see `promql.md`). The f-string uses doubled braces `{{ }}` to write literal braces.

```python
    def _slow_dependency(self) -> SlowFinding:
        plan = self._plan
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        before_load = self._traffic(plan.slow_phase_requests, 4)
        self._settle()
        before = self._route_p95(before_load.finished_at - before_load.started_at + 45)

        self._compose.recreate_app(include_user_id=False, slow_tenant=SLOW_TENANT, prometheus_config=GUARDED_CONFIG)
        after_load = self._traffic(plan.slow_phase_requests, 5)
        self._settle()
        after = self._route_p95(after_load.finished_at - after_load.started_at + 45)

        expected_slow = after_load.requests_per_tenant[SLOW_TENANT]
        query = (
            f'{{ name = "checkout" && span.tenant.id = "{SLOW_TENANT}" && span.route = "checkout" && duration > 1s }}'
        )
        hits = self._tempo.wait_for_search(
            lambda: self._tempo.search_traceql(query, after_load.started_at - 5, after_load.finished_at + 30),
            expected_at_least=expected_slow,
        )
        return SlowFinding(
            route_p95_before_seconds=before,
            route_p95_after_seconds=after,
            tenant_share=expected_slow / max(after_load.sent, 1),
            traces_found=len(hits),
            shortest_slow_span_seconds=min((hit.duration_ms for hit in hits), default=0.0) / 1000,
            expected_slow_requests=expected_slow,
        )
```

Phase 6, **hidden slow dependency**: first traffic with the rule off gives the p95 *before*; then the app restarts with `SLOW_TENANT=tenant-0007` and the same amount of traffic gives the p95 *after*. That tenant is under one percent of requests, so the route's p95 barely moves; the metrics hide the problem. The TraceQL query `{ name = "checkout" && span.tenant.id = "tenant-0007" && span.route = "checkout" && duration > 1s }` finds the slow requests from the traces: `wait_for_search` polls until Tempo has as many hits as the number of requests sent for that tenant. `min((hit.duration_ms for hit in hits), default=0.0)` is the shortest slow trace; `default` avoids an error when there are no hits.

```python
def render_report(report: Report) -> str:
    """The run as the table the README quotes."""
    base, blown, fixed, guarded = report.baseline, report.blown_up, report.fixed, report.guarded
    label, label_values = report.diagnosis.top_label
    metric, metric_series = report.diagnosis.top_metric
    slow = report.slow
    lines = [
        f"Plan: {report.plan.users} users, {report.plan.requests} requests",
        "",
        f"Expected series for the app (1 route x 1 method x {STATUS_VALUES} statuses): "
        f"counter {report.expected.counter_series}, histogram {report.expected.histogram_series}, "
        f"total {report.expected.total}",
        "",
        f"{'':28}{'series':>10}{'memory MB':>12}{'query ms':>10}{'samples/scrape':>16}",
        _row("baseline", base),
        _row("with user_id", blown),
        _row("after the fix (fresh TSDB)", fixed),
        _row("user_id re-added, guarded", guarded),
        f"series growth with user_id: {report.series_growth:.0f}x "
        f"({report.distinct_users} distinct users in the traffic)",
        "",
        f"Offender from /api/v1/status/tsdb: label '{label}' has {label_values} values; "
        f"metric '{metric}' has {metric_series} series.",
        f"Traces for {report.probe_user}: {report.probe_user_traces} found, "
        f"{report.probe_user_requests} requests sent.",
        "",
        f"Hidden slow dependency ({SLOW_TENANT}, {slow.tenant_share:.2%} of traffic): "
        f"route p95 {slow.route_p95_before_seconds * 1000:.1f} ms -> {slow.route_p95_after_seconds * 1000:.1f} ms.",
        f"Trace query on tenant + route + duration > 1 s: {slow.traces_found} traces of {slow.expected_slow_requests} "
        f"slow requests, shortest {slow.shortest_slow_span_seconds * 1000:.0f} ms.",
    ]
    return "\n".join(lines)
```

`render_report` prints the table the README quotes. Inside an f-string, `{'':28}` pads an empty string to 28 characters, `{'series':>10}` right-aligns in 10, and `:.2%` formats a fraction as a percentage with two decimals. The `lines` list is joined with line breaks.

```python
def _row(name: str, measurement: Measurement) -> str:
    return (
        f"{name:28}{measurement.head_series:>10}{measurement.memory_megabytes:>12.0f}"
        f"{measurement.query.wall_milliseconds:>10.0f}{measurement.samples_per_scrape:>16}"
    )


__all__ = [
    "JOB",
    "SLOW_TENANT",
    "Report",
    "ScenarioPlan",
    "ScenarioRunner",
    "SlowFinding",
    "TraceHit",
    "render_report",
    "user_name",
]
```

`_row` formats one measurement as a table row (`:>12.0f` is right-aligned, width 12, no decimals). `__all__` lists the names that `from module import *` and documentation tools treat as the public interface.

## Try it yourself

```bash
.venv/bin/python -c "from cardinality_lab.domain.series import expected_series; print(expected_series({'route': 1, 'method': 1, 'status': 3}, 5))"
```

Expected: `SeriesEstimate(label_combinations=3, counter_series=3, histogram_series=24)`.

```bash
.venv/bin/python -c "from cardinality_lab.domain.series import expected_series; print(expected_series({'route': 1, 'method': 1, 'status': 3, 'user_id': 50000}, 5).total)"
```

Expected: `1350000`: fifty thousand times the baseline of 27.

```bash
.venv/bin/python -c "from cardinality_lab.domain.identifiers import UserId; UserId('bad id')"
```

Expected: a traceback ending in `InvalidIdentifierError: user id must be 1 to 64 letters, digits, dots, dashes or underscores`.

```bash
.venv/bin/python -c "from cardinality_lab.domain.checkout import OutcomePolicy; p = OutcomePolicy(0.02, 0.01); print([p.decide(d).name for d in (0.0, 0.02, 0.5)])"
```

Expected: `['DECLINED', 'GATEWAY_ERROR', 'APPROVED']`.

```bash
.venv/bin/python -m pytest tests/unit/domain tests/unit/application tests/unit/lab/test_scenario.py -q
```

Expected: all pass, with no Docker running.

## Mistakes people make

- **A mutable default argument.** Writing `def f(items=[])` shares one list between all calls. Use `None` and create the list inside the function. The code in this repository either uses immutable defaults (`()`, `None`, numbers) or `field(default_factory=dict)` in dataclasses.
- **Catching everything.** `except Exception:` hides bugs. This repository catches named errors and lets the rest travel up to one place that logs them and returns a 500 answer.
- **Comparing floats with `==`.** Floating-point numbers carry tiny rounding errors. Tests here compare with ranges or with exact values that are safe (for example `0.25` is exactly representable).
- **Using the wall clock to measure durations.** `time.time()` can jump when the system clock is corrected. Code that measures how long something took uses `time.monotonic()`, which only moves forward.
- **Forgetting that `bool` is an `int`.** In Python `True == 1`. The `OrderId` check rejects booleans on purpose.
- **Installing packages into the system Python.** Use a virtual environment. `make install` creates `.venv` for you.

## Check yourself

1. What is the difference between an image and a container? *An image is the read-only package; a container is a running process started from it.*
2. Why does a Dockerfile copy the dependency file before the source code? *So Docker can reuse the cached install layer when only the source changed.*
3. What happens to files a container writes when the container is removed? *They disappear, unless they were written to a volume or a bind mount.*
4. What does a digest give you that a tag does not? *A tag can be moved to a different image later; a digest always names the same bytes.*
5. Which signal does `docker stop` send first, and what comes after the grace period? *`SIGTERM`; then `SIGKILL`.*

## Further reading

- Python 3.12 documentation: https://docs.python.org/3.12/
- The tutorial: https://docs.python.org/3.12/tutorial/index.html
- The standard library index: https://docs.python.org/3.12/library/index.html
- Type hints (`typing`): https://docs.python.org/3.12/library/typing.html
