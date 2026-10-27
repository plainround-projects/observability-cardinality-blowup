import random

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.identifiers import TenantId, UserId
from cardinality_lab.infrastructure.otel_tracing import OtelRequestTracer
from cardinality_lab.infrastructure.payment_gateway import SimulatedPaymentGateway


def _request(tenant="tenant-0007"):
    return CheckoutRequest(UserId("user-012345"), TenantId(tenant))


def test_the_checkout_span_carries_the_user_tenant_and_route(memory_telemetry):
    tracer = OtelRequestTracer(memory_telemetry.tracer_provider.get_tracer("t"))
    with tracer.span(_request()) as span:
        span.set_outcome(Outcome.APPROVED)
    (recorded,) = memory_telemetry.span_exporter.get_finished_spans()
    assert recorded.name == "checkout"
    assert recorded.attributes["user.id"] == "user-012345"
    assert recorded.attributes["tenant.id"] == "tenant-0007"
    assert recorded.attributes["route"] == "checkout"
    assert recorded.attributes["checkout.outcome"] == "approved"
    assert recorded.status.status_code.name == "UNSET"


def test_a_gateway_error_marks_the_span_as_an_error(memory_telemetry):
    tracer = OtelRequestTracer(memory_telemetry.tracer_provider.get_tracer("t"))
    with tracer.span(_request()) as span:
        span.set_outcome(Outcome.GATEWAY_ERROR)
    (recorded,) = memory_telemetry.span_exporter.get_finished_spans()
    assert recorded.status.status_code.name == "ERROR"


def _gateway(memory_telemetry, sleeps, rule, seed=1):
    return SimulatedPaymentGateway(
        OutcomePolicy(0.0, 0.0),
        rule,
        random.Random(seed),
        memory_telemetry.tracer_provider.get_tracer("t"),
        baseline_seconds=0.002,
        slow_seconds=2.0,
        sleep=sleeps.append,
    )


def test_the_gateway_is_slow_only_for_the_matching_route_and_tenant(memory_telemetry):
    sleeps: list[float] = []
    gateway = _gateway(memory_telemetry, sleeps, SlowDependencyRule("checkout", TenantId("tenant-0007")))
    gateway.charge(_request("tenant-0007"))
    gateway.charge(_request("tenant-0008"))
    assert sleeps == [2.0, 0.002]


def test_the_gateway_opens_a_payment_span_and_returns_the_policy_outcome(memory_telemetry):
    gateway = _gateway(memory_telemetry, [], SlowDependencyRule(None, None))
    assert gateway.charge(_request()) is Outcome.APPROVED
    (span,) = memory_telemetry.span_exporter.get_finished_spans()
    assert span.name == "payment.charge"
    assert span.attributes["tenant.id"] == "tenant-0007"
