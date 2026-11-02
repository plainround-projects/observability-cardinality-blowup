# Flask

## What it is

Flask is a small Python library for writing web applications. You create an `app` object, and tell it which Python function answers which URL path and HTTP method. Flask does the HTTP details: it parses the request, calls your function, turns the return value into a response. It is called a **micro-framework** because it gives you routing, request and response objects and error handling, and leaves everything else (database, login) to other libraries. This repository uses Flask 3.1.

## Why this repository uses it

The checkout app has two routes: `GET /checkout` (the one the load hits) and `GET /healthz`. Flask keeps that surface tiny, and the OpenTelemetry Flask instrumentation turns each request into a server span, which is the parent of the `checkout` span that carries the user id.

## Where it appears

| Path | What it does with Flask |
| --- | --- |
| `src/cardinality_lab/interfaces/http_app.py` | The whole HTTP surface of the app. |
| `tests/unit/interfaces/test_http_app.py` | Calls the app through Flask's test client. |

## How it works underneath

A Flask app is a **WSGI application**. WSGI (Web Server Gateway Interface) is the Python standard for the contract between a web server and an application: the server calls the app as a function with the request data and a callback, and the app returns the response body. Flask itself does not listen on a port; a WSGI server (here, waitress) does, and calls the Flask app for each request.

`@app.get("/order/<int:order_id>")` registers a **route**. The `<int:order_id>` part is a **converter**: it captures that part of the path, converts it to an `int`, and passes it as the argument `order_id`. A path such as `/order/abc` does not match, so Flask answers 404.

A function returns a `Response`, usually made with `jsonify(...)`, which turns a Python dict into a JSON body with the right `Content-Type` header. A return value of `(response, 503)` sets the status code.

`@app.after_request` registers a function that runs on every response before it is sent, and may change it (here: add a header). `@app.errorhandler(SomeError)` registers a function that turns that exception into a response. Flask picks the most specific handler: a handler for `OrderNotFoundError` wins over one for `Exception`.

`app.test_client()` gives a fake client that calls the app directly, without a network, which is how the unit tests exercise the routes.

The OpenTelemetry Flask instrumentation wraps the app so each request becomes a server span, and reads the incoming `traceparent` header.

## Walkthrough of this repository's use

```python
"""The checkout app's HTTP surface."""

from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request
from opentelemetry import trace
from werkzeug.exceptions import HTTPException

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import CheckoutRequest
from cardinality_lab.domain.errors import InvalidIdentifierError
from cardinality_lab.domain.identifiers import TenantId, UserId

_log = logging.getLogger(__name__)
```

`request` is Flask's object for the request being handled; it is only valid inside a route function. `HTTPException` is Werkzeug's base class for HTTP errors. The module imports the use case, the domain types and `InvalidIdentifierError`.

```python
def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    return jsonify({"error": code, "detail": detail}), status
```

`_problem` builds the one JSON shape every error uses, `{"error": "<code>", "detail": "<text>"}`, with a status.

```python
def create_app(checkout: Checkout) -> Flask:
    """Build the Flask app: ``GET /checkout`` (headers ``X-User-Id`` and ``X-Tenant-Id``) and ``GET /healthz``."""
    app = Flask("checkout")
```

`create_app(checkout)` is a **factory**: it builds and returns a new Flask app that uses the given use case. Tests build apps around a stub use case.

```python
    @app.after_request
    def add_trace_id(response: Response) -> Response:
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            response.headers["X-Trace-Id"] = trace.format_trace_id(context.trace_id)
        return response
```

`@app.after_request` runs after every route and may change the response. It reads the current OpenTelemetry span (the server span the instrumentation opened) and, if there is one, sets the response header `X-Trace-Id` to its trace id (32 hex characters). The load generator and the integration test read that header to know which trace belongs to which request.

```python
    @app.get("/checkout")
    def get_checkout() -> tuple[Response, int]:
        outcome = checkout.execute(
            CheckoutRequest(
                user=UserId(request.headers.get("X-User-Id", "")),
                tenant=TenantId(request.headers.get("X-Tenant-Id", "")),
            )
        )
        return jsonify({"outcome": outcome.name.lower()}), outcome.status
```

`@app.get("/checkout")` registers the route for GET. The user and the tenant arrive as **request headers**: `request.headers.get("X-User-Id", "")` reads a header, or an empty string if it is missing. Building `UserId("")` raises `InvalidIdentifierError` (the empty string is not allowed), which an error handler below turns into a 400. So a request without identity never reaches the use case. The use case runs, and the answer is `{"outcome": "approved"}` (the enum name in lower case) with the outcome's own status: 200, 402 or 502.

```python
    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok"})
```

`/healthz` answers `{"status": "ok"}`. The Docker health check calls it every ten seconds; `OTEL_PYTHON_FLASK_EXCLUDED_URLS: healthz` in Compose keeps those calls out of the traces.

```python
    @app.errorhandler(InvalidIdentifierError)
    def invalid_identifier(error: InvalidIdentifierError) -> tuple[Response, int]:
        return _problem(400, "invalid_identifier", str(error))

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> tuple[Response, int]:
        return _problem(error.code or 500, (error.name or "error").lower().replace(" ", "_"), error.description or "")

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> tuple[Response, int]:
        _log.exception("unhandled error")
        return _problem(500, "internal_error", "the service failed; see its logs with this trace id")

    return app
```

Three error handlers. `InvalidIdentifierError` becomes `400 invalid_identifier`. `HTTPException` (Flask's own 404 and 405) becomes the same JSON shape, with the error name lower-cased and spaces turned into underscores (`Not Found` becomes `not_found`). Any other `Exception` is logged with its traceback (`_log.exception`) and answered with a generic `500 internal_error`, so internals do not leak. `return app` ends the factory.

## Try it yourself

```bash
.venv/bin/python -m pytest tests/unit/interfaces/test_http_app.py -q
```

Expected: `10 passed`.

```bash
curl -s -i -H "X-User-Id: user-000001" -H "X-Tenant-Id: tenant-0001" http://127.0.0.1:28082/checkout
```

Expected (needs `make up`): `200` (or occasionally `402` or `502`), an `X-Trace-Id` header and a body such as `{"outcome":"approved"}`.

```bash
curl -s -w "\n%{http_code}\n" http://127.0.0.1:28082/checkout
```

Expected: `{"detail":"user id must be 1 to 64 letters, digits, dots, dashes or underscores","error":"invalid_identifier"}` and `400`.

```bash
curl -s -w "\n%{http_code}\n" http://127.0.0.1:28082/nope
```

Expected: a JSON problem with `not_found` and `404`.

```bash
curl -s http://127.0.0.1:28082/healthz
```

Expected: `{"status":"ok"}`.

## Mistakes people make

- **Running `app.run()` in production.** That is the development server. This repository uses waitress.
- **Handling every error in every route.** One `errorhandler` per error type gives one consistent answer.
- **Returning HTML error pages from an API.** The `HTTPException` handler here turns Flask's own errors (404, 405) into JSON.
- **Global mutable state** shared between requests. The app here only reads objects built at start.

## Check yourself

1. What is WSGI? *The Python standard interface between a web server and an application.*
2. What does `<int:order_id>` do? *Captures the path part, converts it to an int and passes it to the function.*
3. What does `after_request` do? *Runs on each response before it is sent, and can change it.*
4. How does the test client differ from a real client? *It calls the app in-process; there is no network.*
5. Why is `app.run()` not used? *It is the development server, not meant for production.*

## Further reading

- Flask 3.1 documentation: https://flask.palletsprojects.com/en/3.1.x/
- Routing: https://flask.palletsprojects.com/en/3.1.x/quickstart/#routing
- Error handlers: https://flask.palletsprojects.com/en/3.1.x/errorhandling/
- Testing: https://flask.palletsprojects.com/en/3.1.x/testing/
- WSGI: https://peps.python.org/pep-3333/
