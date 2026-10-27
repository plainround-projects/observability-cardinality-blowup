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
