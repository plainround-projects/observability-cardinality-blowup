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
