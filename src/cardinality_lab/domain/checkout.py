"""A checkout request, its possible outcomes and the rule that makes one dependency slow for one slice of traffic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cardinality_lab.domain.identifiers import TenantId, UserId

ROUTE = "checkout"
METHOD = "GET"


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    """Who is checking out, for which tenant, on which route."""

    user: UserId
    tenant: TenantId
    route: str = ROUTE


class Outcome(Enum):
    """What a checkout ends in; the value is the HTTP status the app answers with."""

    APPROVED = 200
    DECLINED = 402
    GATEWAY_ERROR = 502

    @property
    def status(self) -> int:
        """The HTTP status code of this outcome."""
        return int(self.value)


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
