import pytest

from cardinality_lab.domain.checkout import CheckoutRequest, Outcome, OutcomePolicy, SlowDependencyRule
from cardinality_lab.domain.errors import InvalidIdentifierError
from cardinality_lab.domain.identifiers import TenantId, UserId
from cardinality_lab.domain.series import expected_series


@pytest.mark.parametrize("value", ["user-000001", "a", "x" * 64, "tenant_0007", "u.1-2"])
def test_valid_identifiers_are_accepted(value):
    assert UserId(value).value == value
    assert TenantId(value).value == value


@pytest.mark.parametrize("value", ["", " ", "x" * 65, "user 1", "user/1", 'user"1', "üser", "a\nb"])
def test_identifiers_with_odd_characters_or_length_are_rejected(value):
    with pytest.raises(InvalidIdentifierError):
        UserId(value)
    with pytest.raises(InvalidIdentifierError):
        TenantId(value)


@pytest.mark.parametrize(
    ("draw", "outcome"),
    [
        (0.0, Outcome.DECLINED),
        (0.0199, Outcome.DECLINED),
        (0.02, Outcome.GATEWAY_ERROR),
        (0.0299, Outcome.GATEWAY_ERROR),
        (0.03, Outcome.APPROVED),
        (0.999, Outcome.APPROVED),
    ],
)
def test_the_outcome_policy_slices_the_unit_interval(draw, outcome):
    assert OutcomePolicy(0.02, 0.01).decide(draw) is outcome


def test_outcomes_carry_their_http_status():
    assert [outcome.status for outcome in Outcome] == [200, 402, 502]


@pytest.mark.parametrize(("declined", "error"), [(-0.1, 0.0), (0.0, 1.1), (0.6, 0.6)])
def test_the_outcome_policy_rejects_impossible_rates(declined, error):
    with pytest.raises(ValueError, match=r"rates|exceed"):
        OutcomePolicy(declined, error)


def _request(route="checkout", tenant="tenant-0007"):
    return CheckoutRequest(UserId("user-000001"), TenantId(tenant), route)


def test_the_slow_rule_needs_both_the_route_and_the_tenant_to_match():
    rule = SlowDependencyRule("checkout", TenantId("tenant-0007"))
    assert rule.applies(_request())
    assert not rule.applies(_request(tenant="tenant-0008"))
    assert not rule.applies(_request(route="cart"))


def test_a_rule_without_a_route_or_tenant_never_applies():
    assert not SlowDependencyRule(None, TenantId("tenant-0007")).applies(_request())
    assert not SlowDependencyRule("checkout", None).applies(_request())


def test_the_baseline_series_count_is_the_product_of_the_label_cardinalities():
    estimate = expected_series({"route": 1, "method": 1, "status": 3}, finite_buckets=5)
    assert (estimate.label_combinations, estimate.counter_series) == (3, 3)
    assert estimate.histogram_series == 3 * (5 + 1 + 2)
    assert estimate.total == 27


def test_a_user_id_label_multiplies_every_series_by_the_number_of_users():
    safe = expected_series({"route": 1, "method": 1, "status": 3}, 5)
    unsafe = expected_series({"route": 1, "method": 1, "status": 3, "user_id": 50_000}, 5)
    assert unsafe.total == safe.total * 50_000


def test_no_labels_means_one_series_and_negative_counts_are_rejected():
    assert expected_series({}, 0).total == 1 + 3
    with pytest.raises(ValueError, match="negative"):
        expected_series({"route": -1}, 5)
