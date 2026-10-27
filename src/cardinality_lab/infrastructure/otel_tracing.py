"""The OpenTelemetry adapter: where the user id lives, as a span attribute, one value per trace."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry.trace import Span, Status, StatusCode, Tracer

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome

SPAN_NAME = "checkout"


class _OtelRequestSpan:
    def __init__(self, span: Span) -> None:
        self._span = span

    def set_outcome(self, outcome: Outcome) -> None:
        self._span.set_attribute("checkout.outcome", outcome.name.lower())
        self._span.set_attribute("http.response.status_code", outcome.status)
        if outcome is Outcome.GATEWAY_ERROR:
            self._span.set_status(Status(StatusCode.ERROR, "gateway error"))


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
