"""The Prometheus adapter: a request counter and a latency histogram with a deliberate, switchable mistake."""

from __future__ import annotations

from collections.abc import Sequence

from prometheus_client import CollectorRegistry, Counter, Histogram

from cardinality_lab.domain.identifiers import UserId

# Few buckets on purpose: every bucket is one more series per label combination, which is what the lab measures.
LATENCY_BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.05, 0.5, 2.5)
SAFE_LABELS: tuple[str, ...] = ("route", "method", "status")
UNSAFE_LABELS: tuple[str, ...] = (*SAFE_LABELS, "user_id")


class PrometheusCheckoutMetrics:
    """``requests_total`` and ``request_latency_seconds``, labeled by route, method and status.

    With ``include_user_id`` the metrics also carry a ``user_id`` label. That is the lesson's mistake, kept behind a
    switch so the scenario can make it, measure it and undo it without editing code.
    """

    def __init__(
        self,
        registry: CollectorRegistry,
        include_user_id: bool,
        buckets: Sequence[float] = LATENCY_BUCKETS,
    ) -> None:
        """Register the two metrics in ``registry``."""
        self._include_user_id = include_user_id
        labels = UNSAFE_LABELS if include_user_id else SAFE_LABELS
        self._requests = Counter("requests", "Requests handled.", labels, registry=registry)
        self._latency = Histogram(
            "request_latency_seconds", "Request latency.", labels, buckets=tuple(buckets), registry=registry
        )

    def record(self, route: str, method: str, status: int, user: UserId, duration_seconds: float) -> None:
        """Count the request and observe its latency."""
        values = {"route": route, "method": method, "status": str(status)}
        if self._include_user_id:
            values["user_id"] = user.value
        self._requests.labels(**values).inc()
        self._latency.labels(**values).observe(duration_seconds)
