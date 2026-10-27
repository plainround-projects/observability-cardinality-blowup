from contextlib import contextmanager

from cardinality_lab.application.checkout import Checkout
from cardinality_lab.domain.checkout import CheckoutRequest, Outcome
from cardinality_lab.domain.identifiers import TenantId, UserId

REQUEST = CheckoutRequest(UserId("user-000042"), TenantId("tenant-0007"))


class Gateway:
    def __init__(self, outcome):
        self.outcome = outcome

    def charge(self, request):
        return self.outcome


class Metrics:
    def __init__(self):
        self.records = []

    def record(self, route, method, status, user, duration_seconds):
        self.records.append((route, method, status, user.value, duration_seconds))


class Tracer:
    def __init__(self):
        self.requests, self.outcomes = [], []

    @contextmanager
    def span(self, request):
        self.requests.append(request)
        yield self

    def set_outcome(self, outcome):
        self.outcomes.append(outcome)


class Clock:
    def __init__(self):
        self.now = 10.0

    def monotonic(self):
        self.now += 0.5
        return self.now


def _run(outcome):
    metrics, tracer = Metrics(), Tracer()
    result = Checkout(Gateway(outcome), metrics, tracer, Clock()).execute(REQUEST)
    return result, metrics, tracer


def test_an_approved_checkout_is_counted_with_its_status_and_duration_and_traced_with_the_request():
    result, metrics, tracer = _run(Outcome.APPROVED)
    assert result is Outcome.APPROVED
    assert metrics.records == [("checkout", "GET", 200, "user-000042", 0.5)]
    assert tracer.requests == [REQUEST]
    assert tracer.outcomes == [Outcome.APPROVED]


def test_declined_and_failed_checkouts_are_counted_too(caplog):
    with caplog.at_level("WARNING"):
        _, declined, _ = _run(Outcome.DECLINED)
        _, failed, _ = _run(Outcome.GATEWAY_ERROR)
    assert declined.records[0][2] == 402
    assert failed.records[0][2] == 502
    assert [record.outcome for record in caplog.records] == ["DECLINED", "GATEWAY_ERROR"]
    assert caplog.records[0].tenant == "tenant-0007"


def test_an_approved_checkout_logs_nothing(caplog):
    with caplog.at_level("INFO"):
        _run(Outcome.APPROVED)
    assert caplog.records == []
