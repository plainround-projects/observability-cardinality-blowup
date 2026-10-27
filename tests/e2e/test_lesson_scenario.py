"""The whole lesson at a tenth of its size, asserted number by number against the real stack."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cardinality_lab.lab.compose import Compose
from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.scenario import Report, ScenarioPlan, ScenarioRunner, render_report
from cardinality_lab.lab.tempo import TempoClient

pytestmark = pytest.mark.e2e

USERS = 5_000
REQUESTS = 20_000


@pytest.fixture(scope="module")
def report() -> Report:
    env = os.environ
    plan = ScenarioPlan(f"http://127.0.0.1:{env.get('APP_HOST_PORT', '28082')}", USERS, REQUESTS)
    runner = ScenarioRunner(
        plan,
        Compose(Path(__file__).resolve().parents[2], env),
        PrometheusClient(f"http://127.0.0.1:{env.get('PROMETHEUS_HOST_PORT', '9090')}"),
        TempoClient(f"http://127.0.0.1:{env.get('TEMPO_HOST_PORT', '3200')}"),
    )
    result = runner.run()
    print(render_report(result))
    return result


def test_step_1_the_expected_series_count_is_computed_from_the_labels(report):
    assert report.expected.counter_series == 3
    assert report.expected.histogram_series == 3 * (5 + 1 + 2)


def test_step_2_a_user_id_label_grows_series_memory_and_samples_by_orders_of_magnitude(report):
    assert report.series_growth >= 10
    assert report.blown_up.resident_memory_bytes > report.baseline.resident_memory_bytes
    assert report.blown_up.samples_per_scrape >= 10 * report.baseline.samples_per_scrape
    assert report.blown_up.query.engine_milliseconds >= report.baseline.query.engine_milliseconds


def test_step_3_the_top_label_in_the_backends_own_statistics_is_user_id(report):
    label, values = report.diagnosis.top_label
    assert label == "user_id"
    assert values >= 0.9 * report.distinct_users
    assert report.diagnosis.top_metric[0].startswith("request_latency_seconds")


def test_step_4_the_series_count_returns_near_baseline_and_one_users_requests_are_still_findable(report):
    assert report.fixed.head_series <= 2 * report.baseline.head_series
    assert report.fixed.samples_per_scrape <= 2 * report.baseline.samples_per_scrape
    assert report.probe_user_traces == report.probe_user_requests


def test_step_4_the_guard_keeps_a_re_added_label_from_creating_series(report):
    assert report.guarded.head_series <= 2 * report.baseline.head_series
    assert report.guarded.samples_per_scrape <= 2 * report.baseline.samples_per_scrape


def test_step_5_traces_find_the_slow_dependency_that_the_route_p95_hides(report):
    slow = report.slow
    assert slow.expected_slow_requests >= 20
    assert slow.traces_found >= 0.9 * slow.expected_slow_requests
    assert slow.shortest_slow_span_seconds >= 2.0
    assert slow.tenant_share < 0.01
    assert slow.route_p95_after_seconds <= max(2 * slow.route_p95_before_seconds, 0.05)
