"""Configuration read once from the environment and validated (twelve-factor)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class SettingsError(ValueError):
    """An environment variable is missing or has an unusable value."""


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float) -> float:
    raw = env.get(name)
    try:
        value = float(raw) if raw not in (None, "") else default
    except ValueError as error:
        raise SettingsError(f"{name} must be a number, got {raw!r}") from error
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}, got {value}")
    return value


def _flag(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "false").strip().lower()
    if raw not in {"true", "false"}:
        raise SettingsError(f"{name} must be true or false, got {raw!r}")
    return raw == "true"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Everything the checkout app reads from its environment."""

    service_name: str
    bind_host: str
    port: int
    metrics_port: int
    metrics_include_user_id: bool
    declined_rate: float
    error_rate: float
    seed: int | None
    baseline_gateway_seconds: float
    slow_route: str
    slow_tenant: str
    slow_seconds: float
    log_level: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AppSettings:
        """Build the settings, raising ``SettingsError`` for an invalid variable."""
        level = env.get("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise SettingsError(f"LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {level!r}")
        seed = env.get("SEED", "")
        return cls(
            service_name=env.get("OTEL_SERVICE_NAME", "checkout"),
            bind_host=env.get("BIND_HOST", "127.0.0.1"),
            port=int(_number(env, "APP_PORT", 8080, 1, 65535)),
            metrics_port=int(_number(env, "METRICS_PORT", 9100, 1, 65535)),
            metrics_include_user_id=_flag(env, "METRICS_INCLUDE_USER_ID"),
            declined_rate=_number(env, "DECLINED_RATE", 0.02, 0.0, 1.0),
            error_rate=_number(env, "GATEWAY_ERROR_RATE", 0.01, 0.0, 1.0),
            seed=int(seed) if seed else None,
            baseline_gateway_seconds=_number(env, "BASELINE_GATEWAY_SECONDS", 0.002, 0.0, 5.0),
            slow_route=env.get("SLOW_ROUTE", "checkout"),
            slow_tenant=env.get("SLOW_TENANT", ""),
            slow_seconds=_number(env, "SLOW_SECONDS", 2.0, 0.0, 30.0),
            log_level=level,
        )
