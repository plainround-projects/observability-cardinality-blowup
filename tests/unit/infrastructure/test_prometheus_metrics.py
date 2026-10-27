import pytest
from prometheus_client import CollectorRegistry, disable_created_metrics, generate_latest

from cardinality_lab.domain.identifiers import UserId
from cardinality_lab.infrastructure.prometheus_metrics import LATENCY_BUCKETS, PrometheusCheckoutMetrics


@pytest.fixture(autouse=True, scope="module")
def _without_created_series():
    # The app does this once at start-up (interfaces/main.py); the flag is process-wide.
    disable_created_metrics()


def _series(registry):
    return [line for line in generate_latest(registry).decode().splitlines() if line and not line.startswith("#")]


def _drive(include_user_id, users):
    registry = CollectorRegistry()
    metrics = PrometheusCheckoutMetrics(registry, include_user_id)
    for number in range(users):
        metrics.record("checkout", "GET", 200, UserId(f"user-{number:06d}"), 0.004)
    return _series(registry)


def test_without_the_user_label_the_series_count_does_not_depend_on_the_users():
    assert len(_drive(False, 5)) == len(_drive(False, 500))


def test_baseline_series_for_one_status_are_one_counter_plus_the_histogram_buckets_sum_and_count():
    assert len(_drive(False, 3)) == 1 + (len(LATENCY_BUCKETS) + 1 + 2)


def test_with_the_user_label_every_user_adds_a_full_set_of_series():
    per_user = 1 + (len(LATENCY_BUCKETS) + 1 + 2)
    assert len(_drive(True, 200)) == 200 * per_user


def test_the_unsafe_mode_exposes_the_user_id_label_and_the_safe_mode_does_not():
    assert any('user_id="user-000000"' in line for line in _drive(True, 1))
    assert not any("user_id" in line for line in _drive(False, 1))


def test_observations_land_in_the_matching_bucket_and_the_counter_counts_requests():
    registry = CollectorRegistry()
    metrics = PrometheusCheckoutMetrics(registry, False)
    for _ in range(3):
        metrics.record("checkout", "GET", 200, UserId("u"), 0.004)
    metrics.record("checkout", "GET", 502, UserId("u"), 3.0)
    assert registry.get_sample_value("requests_total", {"route": "checkout", "method": "GET", "status": "200"}) == 3
    assert (
        registry.get_sample_value(
            "request_latency_seconds_bucket", {"route": "checkout", "method": "GET", "status": "200", "le": "0.005"}
        )
        == 3
    )
    assert registry.get_sample_value("requests_total", {"route": "checkout", "method": "GET", "status": "502"}) == 1
