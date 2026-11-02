# JSON

## What it is

JSON (JavaScript Object Notation) is a text format for data. It has objects (`{"key": value}`), arrays (`[1, 2, 3]`), strings in double quotes, numbers, `true`, `false` and `null`. It is the common language that programs use to talk over HTTP, and it is also the file format of Grafana dashboards. JSON has no comments and does not allow a trailing comma.

## Why this repository uses it

JSON appears at four levels: the **dashboard file** (Grafana's native format), the **answers of the Prometheus and Tempo APIs** that the lab client parses, the **HTTP answers of the app** (`{"outcome": "approved"}` and the error problems), and the **log lines** (one JSON object per line).

## Where it appears

| Where | What |
| --- | --- |
| `observability/grafana/dashboards/cardinality-blowup.json` | The dashboard (see `grafana.md` for every field). |
| `src/cardinality_lab/interfaces/http_app.py` | `jsonify` answers. |
| `src/cardinality_lab/infrastructure/logging_setup.py` | One JSON object per log line. |
| `src/cardinality_lab/lab/prometheus.py`, `lab/tempo.py` | Read JSON from the APIs. |
| `tests/observability/test_configuration_as_code.py` | Loads the dashboard with `json.loads`. |

## How it works underneath

A program that sends JSON turns an in-memory structure into text (**serializing**, `json.dumps` in Python). A program that receives it turns the text back into a structure (**parsing**, `json.loads`). Python maps JSON objects to `dict`, arrays to `list`, strings to `str`, numbers to `int` or `float`, `true`/`false` to `True`/`False` and `null` to `None`.

Keys of an object are always strings. Numbers have no size limit in the format, but some programs store them as 64-bit floats, so very large integers can lose precision. That is one reason ids that are long (such as the 128-bit trace id) are sent as hexadecimal strings.

**Structured logging** writes one JSON object per line ("JSON Lines"). Each line is self-describing, so a log store can search by field.

## Walkthrough of this repository's use

**An answer of the app.** `jsonify({"outcome": outcome.name.lower()})` writes `{"outcome":"approved"}`; an error is a problem object with two keys:

```python
def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    return jsonify({"error": code, "detail": detail}), status
```

**What Prometheus answers.** The client reads this shape, shown in the unit test's fake:

```python
def _instant(value):
    return Response(
        {
            "status": "success",
            "data": {"result": [{"value": [0, str(value)]}], "stats": {"timings": {"evalTotalTime": 0.0123}}},
        }
    )
```

`status` is `success`, `data.result` is a list of series, each with `value` as `[timestamp, "number"]` (the number is a string, so the client calls `float(...)`), and `data.stats.timings.evalTotalTime` is the engine's own time in seconds.

**What the statistics endpoint answers.**

```python
    body = {
        "status": "success",
        "data": {
            "seriesCountByMetricName": [{"name": "request_latency_seconds_bucket", "value": 350000}],
            "labelValueCountByLabelName": [{"name": "user_id", "value": 49000}, {"name": "status", "value": 3}],
        },
    }
```

`seriesCountByMetricName` and `labelValueCountByLabelName` are lists of `{"name": ..., "value": ...}` objects, largest first.

**A log line.** The formatter builds a dict and writes it with `json.dumps`:

```python
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "logger": record.name,
            "service": self._service_name,
        }
```

**The dashboard.** A dashboard is one JSON object with `panels` (an array). Inside a JSON string every `"` is written `\"`, so a PromQL label matcher looks like this in the file:

```json
          "expr": "process_resident_memory_bytes{job=\"prometheus\"}",
```

`{job=\"prometheus\"}` is the text `{job="prometheus"}`. The dashboard and the datasource files are linted by loading them:

```python
@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return dict(json.loads((OBSERVABILITY / "grafana" / "dashboards" / "cardinality-blowup.json").read_text()))
```

## Try it yourself

```bash
python3 -m json.tool observability/grafana/dashboards/cardinality-blowup.json | head -8
```

Expected: the file pretty-printed; the command fails with a position if it is not valid JSON.

```bash
curl -s -H "X-User-Id: user-000001" -H "X-Tenant-Id: tenant-0001" http://127.0.0.1:28082/checkout
```

Expected (needs `make up`): `{"outcome":"approved"}` (or `declined` or `gateway_error` for the occasional simulated failure).

```bash
curl -s "http://127.0.0.1:29090/api/v1/query?query=up" | python3 -m json.tool | head -20
```

Expected: `"status": "success"` and a `result` list with `[timestamp, "1"]` values.

```bash
python3 -c "import json; print(json.dumps({'user': 'user-000001', 'ok': True, 'tags': None}))"
```

Expected: `{"user": "user-000001", "ok": true, "tags": null}`.

```bash
python3 -c "import json; json.loads('{\"a\": 1,}')"
```

Expected: a `JSONDecodeError` about the trailing comma.

## Mistakes people make

- **A trailing comma** or single quotes: invalid JSON.
- **Assuming key order** matters. It does not for the data's meaning.
- **Putting JSON in a string and forgetting to escape quotes.** Inside a JSON string every `"` must be written `\"`. The dashboard's PromQL expressions show this.
- **Hand-editing large JSON.** Dashboards here are code-reviewed and linted by tests.

## Check yourself

1. Which quotes does JSON require for strings? *Double quotes.*
2. Does JSON allow comments? *No.*
3. What does `json.dumps` do? *Turns a Python structure into JSON text.*
4. How do you write a double quote inside a JSON string? *With a backslash: `\"`.*
5. Why is a trace id sent as a hex string and not a number? *It is 128 bits, which many programs cannot hold exactly as a number.*

## Further reading

- JSON specification (RFC 8259): https://www.rfc-editor.org/rfc/rfc8259
- Python `json` module: https://docs.python.org/3.12/library/json.html
