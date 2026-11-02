# Python logging (standard library)

## What it is

`logging` is the module of Python's standard library for writing **log lines**: short messages that say what a program is doing. A log line has a **level** (how serious it is: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`), a message, a time and the name of the **logger** that wrote it. A **logger** is a named object you ask for with `logging.getLogger("name")` and write to with `logger.info("text")`. A **handler** decides where lines go (the screen, a file, the network). A **formatter** decides how a line is written as text. Loggers have a tree of names separated by dots: a logger named `cardinality_lab.application.assemble_order` hands its records up to its parent loggers, and finally to the **root logger**, where the handlers are attached.

## Why this repository uses it

The app logs only when something is not normal (a declined or failed checkout, an unhandled error), and every line must be searchable and tied to its trace. The formatter writes one JSON object per line and adds the **trace id** and **span id** of the request being handled. The code that writes the lines (`_log.warning("checkout not approved", extra={...})`) does not know about OpenTelemetry. In this lab logs go to the container's standard output only (`OTEL_LOGS_EXPORTER` is `none`); the lesson's stores are Prometheus and Tempo.

## Where it appears

| Path | What it does with logging |
| --- | --- |
| `src/cardinality_lab/infrastructure/logging_setup.py` | The JSON formatter and the function that wires the root logger. |
| `src/cardinality_lab/application/checkout.py` | Writes a `WARNING` for a declined or failed checkout. |
| `src/cardinality_lab/interfaces/http_app.py`, `server.py` | Write the unhandled-error line, and the "listening" and "stopped" lines. |
| `tests/unit/infrastructure/test_logging_setup.py` | Tests the formatter. |

## How it works underneath

When code calls `logger.info("text", extra={"order_id": 5})`, the logger first compares the level with its own threshold; if the level is too low the call ends. Otherwise it builds a **LogRecord** object: message, level, time (`record.created`, seconds since 1970), logger name, and every key of `extra` set as an attribute on the record. Then it passes the record to its own handlers and up the tree to the parents' handlers. Each handler calls its formatter's `format(record)` to get a string and writes it.

The OpenTelemetry SDK can also ship records over OTLP with its own `LoggingHandler`; this repository does not attach it, because logs are not one of the stores of this lesson (the sister repository `observability-three-signals` does).

Standard attributes of a record (`name`, `msg`, `levelname`, `created`, ...) are always present. Anything else on `record.__dict__` was added by `extra=`, and the formatter in this repository copies those into the JSON output.

## Walkthrough of this repository's use

```python
"""Structured JSON logging with the trace and span ids on every line."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import IO, Any

from opentelemetry import trace
```

The imports: `json` writes JSON text; `logging` is the module being explained; `sys.stdout` is the standard output stream; `datetime` and `UTC` format the time; `IO` and `Any` are only type hints; `trace` is the OpenTelemetry trace API, used to read the current span.

```python
# Attributes every LogRecord has; anything else on a record came from ``extra=`` and is emitted as a field.
_STANDARD_FIELDS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
```

`logging.makeLogRecord({})` builds an empty record; `vars(...)` is its dictionary of attributes; `frozenset(...)` makes the keys an unchangeable set. `| {"message", "asctime", "taskName"}` adds three more names that the logging machinery may add later. Everything that is **not** in this set came from `extra=`.

```python
class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON object, adding the current span's ids as ``trace_id`` and ``span_id``."""

    def __init__(self, service_name: str) -> None:
        """Remember the service name that goes into every line."""
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
```

`JsonFormatter` inherits from `logging.Formatter` and replaces its `format` method. The constructor calls `super().__init__()` and remembers the service name.

```python
    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a single-line JSON document."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
            "service": self._service_name,
        }
```

`format` starts a dictionary `payload` with the standard fields. `datetime.fromtimestamp(record.created, tz=UTC)` converts the record's time to a time-zone-aware date; `.isoformat(timespec="milliseconds")` writes it like `2026-10-27T01:55:48.813+00:00`. `record.levelname.lower()` gives `warning`. `record.getMessage()` returns the message text. `record.name` is the logger name.

```python
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            payload["trace_id"] = trace.format_trace_id(context.trace_id)
            payload["span_id"] = trace.format_span_id(context.span_id)
```

`trace.get_current_span()` returns the span active right now (an invalid, do-nothing span when none is active). `context.is_valid` is true for a real span. `trace.format_trace_id` writes the 128-bit id as 32 hexadecimal characters and `format_span_id` the 64-bit span id as 16, as `trace_id` and `span_id`.

```python
        payload.update({key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
```

`payload.update({...})` adds every `extra` field (for example `outcome` and `tenant`). If an exception is being handled (`record.exc_info`), `self.formatException(...)` produces the traceback text. `json.dumps(payload, default=str)` writes one line of JSON; `default=str` makes any value JSON cannot encode fall back to its text form.

```python
def configure_logging(level: str, service_name: str, stream: IO[str] | None = None) -> None:
    """Send JSON log lines to ``stream`` (stdout), replacing any handler installed earlier."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)
    console = logging.StreamHandler(stream or sys.stdout)
    console.setFormatter(JsonFormatter(service_name))
    root.addHandler(console)
```

`configure_logging(level, service_name, stream=None)` is called once at start-up. It removes every handler already installed (so calling it twice never doubles the lines; a unit test checks that), sets the level, and adds one `StreamHandler` writing to `stream` or to standard output with the JSON formatter. Standard output is the container convention: Docker collects it with `docker logs`. The Compose file sets `LOG_LEVEL: WARNING`, so only warnings and errors are written during the big runs.

## Try it yourself

```bash
.venv/bin/python -c "
import logging
from cardinality_lab.infrastructure.logging_setup import configure_logging
configure_logging('INFO', 'demo')
logging.getLogger('x').info('hello', extra={'order_id': 5})"
```

Expected: one line of JSON with `"msg": "hello"`, `"service": "demo"` and `"order_id": 5`, and no `trace_id` (no span is active).

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_logging_setup.py -q
```

Expected: `4 passed`.

```bash
docker compose logs app | tail -3
```

Expected (needs `make up` and some declined requests): JSON lines such as `"msg": "checkout not approved"`, each with `trace_id`, `span_id`, `outcome` and `tenant`.

## Mistakes people make

- **Building the message with an f-string inside the call** (`logger.info(f"order {id}")`). Prefer a fixed message plus `extra={...}`: fixed messages are easy to search for, and each field becomes a separate key. This repository does that.
- **Logging secrets or personal data.** None of the fields here are sensitive.
- **Adding handlers every time a function runs**, which duplicates lines. `configure_logging` removes the old ones first.
- **Using `print`.** It has no level, no time and no structure.
- **Configuring logging in a library.** Only the entry points call `configure_logging`.

## Check yourself

1. What is the difference between a logger and a handler? *A logger is what code writes to; a handler decides where the record goes.*
2. How do `extra={"order_id": 5}` values reach the JSON? *They become attributes on the record; the formatter copies every attribute that is not a standard field.*
3. Why is `trace_id` written as hex? *It is a 128-bit number; hex text is the standard form for ids and is what Loki and Tempo expect.*
4. Why does `configure_logging` remove existing handlers first? *So repeated calls do not write each line more than once.*
5. Why do both handlers share one formatter? *So the line in Loki is identical to the line on the console.*

## Further reading

- Python 3.12 `logging`: https://docs.python.org/3.12/library/logging.html
- Logging HOWTO: https://docs.python.org/3.12/howto/logging.html
- `LogRecord` attributes: https://docs.python.org/3.12/library/logging.html#logrecord-attributes
- OpenTelemetry Python logs: https://opentelemetry.io/docs/languages/python/instrumentation/#logs
