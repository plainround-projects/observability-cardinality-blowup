"""Against the stack that `make up` started: the baseline app exposes only bounded labels and the stores answer."""

from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.tempo import TempoClient

pytestmark = pytest.mark.integration

APP = f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '28082')}"
PROMETHEUS = PrometheusClient(f"http://127.0.0.1:{os.environ.get('PROMETHEUS_HOST_PORT', '29090')}")
TEMPO = TempoClient(f"http://127.0.0.1:{os.environ.get('TEMPO_HOST_PORT', '23200')}")


def test_the_app_answers_a_checkout_and_rejects_a_request_without_identity():
    ok = requests.get(f"{APP}/checkout", headers={"X-User-Id": "user-000001", "X-Tenant-Id": "tenant-0001"}, timeout=10)
    assert ok.status_code in {200, 402, 502}
    assert len(ok.headers["X-Trace-Id"]) == 32
    assert requests.get(f"{APP}/checkout", timeout=10).status_code == 400


def test_prometheus_scrapes_the_app_and_the_series_carry_only_route_method_and_status():
    for number in range(30):
        requests.get(
            f"{APP}/checkout", headers={"X-User-Id": f"user-{number:06d}", "X-Tenant-Id": "tenant-0001"}, timeout=10
        )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and not PROMETHEUS.scalar('up{job="checkout"}'):
        time.sleep(2)
    assert PROMETHEUS.scalar('up{job="checkout"}') == 1
    series = 'count(requests_total{job="checkout",route="checkout"})'
    while time.monotonic() < deadline and not PROMETHEUS.scalar(series):
        time.sleep(2)
    # Ask for the series directly: the TSDB statistics list only the labels with the most values, and a label with
    # one value ("route") can fall outside that list on a Prometheus with many labels of its own.
    assert PROMETHEUS.scalar(series) > 0
    assert PROMETHEUS.scalar('count({job="checkout",user_id!=""})') == 0


def test_one_request_leaves_exactly_one_trace_findable_by_its_user_id():
    user = f"user-{uuid.uuid4().hex[:12]}"
    started = time.time()
    requests.get(f"{APP}/checkout", headers={"X-User-Id": user, "X-Tenant-Id": "tenant-0002"}, timeout=10)
    hits = TEMPO.wait_for_search(lambda: TEMPO.search_by_tags({"user.id": user}, started - 5, time.time() + 30), 1)
    assert len(hits) == 1
