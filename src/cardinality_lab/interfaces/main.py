"""Composition root: read settings, build the adapters, expose /metrics on its own port, serve."""

from __future__ import annotations

import os
import random
import time

from opentelemetry import trace
from prometheus_client import REGISTRY, disable_created_metrics, start_http_server

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.identifiers import TenantId
from cardinality_lab.infrastructure.logging_setup import configure_logging
from cardinality_lab.infrastructure.otel_tracing import OtelRequestTracer
from cardinality_lab.infrastructure.payment_gateway import SimulatedPaymentGateway
from cardinality_lab.infrastructure.prometheus_metrics import PrometheusCheckoutMetrics
from cardinality_lab.infrastructure.settings import AppSettings
from cardinality_lab.interfaces.http_app import create_app
from cardinality_lab.interfaces.server import run_server


class _MonotonicClock:
    def monotonic(self) -> float:
        return time.monotonic()


def main() -> None:
    """Start the checkout app."""
    settings = AppSettings.from_env(os.environ)
    configure_logging(settings.log_level, settings.service_name)
    # The `_created` series double the count of every counter and histogram and carry no information here.
    disable_created_metrics()
    metrics = PrometheusCheckoutMetrics(REGISTRY, settings.metrics_include_user_id)
    tracer = trace.get_tracer("cardinality_lab")
    rule = SlowDependencyRule(
        settings.slow_route or None, TenantId(settings.slow_tenant) if settings.slow_tenant else None
    )
    gateway = SimulatedPaymentGateway(
        OutcomePolicy(settings.declined_rate, settings.error_rate),
        rule,
        random.Random(settings.seed),
        tracer,
        settings.baseline_gateway_seconds,
        settings.slow_seconds,
    )
    checkout = Checkout(gateway, metrics, OtelRequestTracer(tracer), _MonotonicClock())
    start_http_server(settings.metrics_port, addr=settings.bind_host)
    run_server(create_app(checkout), settings.bind_host, settings.port)
