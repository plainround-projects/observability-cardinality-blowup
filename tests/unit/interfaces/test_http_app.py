import pytest

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import Outcome
from cardinality_lab.interfaces.http_app import create_app


class StubCheckout(Checkout):
    def __init__(self, outcome=Outcome.APPROVED, error=None):
        self._outcome, self._error, self.seen = outcome, error, []

    def execute(self, request):
        self.seen.append(request)
        if self._error:
            raise self._error
        return self._outcome


HEADERS = {"X-User-Id": "user-000042", "X-Tenant-Id": "tenant-0007"}


def test_a_checkout_passes_the_user_and_tenant_headers_to_the_use_case():
    stub = StubCheckout()
    response = create_app(stub).test_client().get("/checkout", headers=HEADERS)
    assert (response.status_code, response.get_json()) == (200, {"outcome": "approved"})
    assert (stub.seen[0].user.value, stub.seen[0].tenant.value, stub.seen[0].route) == (
        "user-000042",
        "tenant-0007",
        "checkout",
    )


@pytest.mark.parametrize(("outcome", "status"), [(Outcome.DECLINED, 402), (Outcome.GATEWAY_ERROR, 502)])
def test_outcomes_become_their_http_status(outcome, status):
    response = create_app(StubCheckout(outcome)).test_client().get("/checkout", headers=HEADERS)
    assert response.status_code == status


@pytest.mark.parametrize(
    "headers", [{}, {"X-User-Id": "user-1"}, {"X-Tenant-Id": "t"}, {"X-User-Id": "bad id", "X-Tenant-Id": "t"}]
)
def test_missing_or_malformed_identifiers_are_a_bad_request_and_never_reach_the_use_case(headers):
    stub = StubCheckout()
    response = create_app(stub).test_client().get("/checkout", headers=headers)
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_identifier"
    assert stub.seen == []


def test_unexpected_failures_are_a_json_500():
    response = create_app(StubCheckout(error=RuntimeError("bug"))).test_client().get("/checkout", headers=HEADERS)
    assert (response.status_code, response.get_json()["error"]) == (500, "internal_error")


def test_unknown_routes_are_a_json_404_and_health_is_ok():
    client = create_app(StubCheckout()).test_client()
    assert client.get("/nope").get_json()["error"] == "not_found"
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_responses_inside_a_span_carry_the_trace_id(memory_telemetry):
    client = create_app(StubCheckout()).test_client()
    with memory_telemetry.tracer_provider.get_tracer("t").start_as_current_span("request") as span:
        response = client.get("/healthz")
        expected = f"{span.get_span_context().trace_id:032x}"
    assert response.headers["X-Trace-Id"] == expected
