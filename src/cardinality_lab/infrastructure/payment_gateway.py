"""A simulated payment gateway: fast for everyone, slow for one route and one tenant."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from opentelemetry.trace import Tracer

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule


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

    def charge(self, request: CheckoutRequest) -> Outcome:
        """Call the 'downstream' inside its own span and return the outcome."""
        slow = self._rule.applies(request)
        with self._tracer.start_as_current_span("payment.charge") as span:
            span.set_attribute("peer.service", "payment-gateway")
            span.set_attribute("tenant.id", request.tenant.value)
            self._sleep(self._slow_seconds if slow else self._baseline_seconds)
            return self._policy.decide(self._rng.random())
