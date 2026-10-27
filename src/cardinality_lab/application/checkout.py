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
