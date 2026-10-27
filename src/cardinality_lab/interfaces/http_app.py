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


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    return jsonify({"error": code, "detail": detail}), status


def create_app(checkout: Checkout) -> Flask:
    """Build the Flask app: ``GET /checkout`` (headers ``X-User-Id`` and ``X-Tenant-Id``) and ``GET /healthz``."""
    app = Flask("checkout")

    @app.after_request
    def add_trace_id(response: Response) -> Response:
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            response.headers["X-Trace-Id"] = trace.format_trace_id(context.trace_id)
        return response

    @app.get("/checkout")
    def get_checkout() -> tuple[Response, int]:
        outcome = checkout.execute(
            CheckoutRequest(
                user=UserId(request.headers.get("X-User-Id", "")),
                tenant=TenantId(request.headers.get("X-Tenant-Id", "")),
            )
        )
        return jsonify({"outcome": outcome.name.lower()}), outcome.status

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify({"status": "ok"})

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
