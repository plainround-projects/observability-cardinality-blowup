import pytest

from cardinality_lab.lab.prometheus import PrometheusClient, PrometheusError


class Response:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        path = url.split("9090", 1)[1]
        self.calls.append((path, params))
        reply = self.routes[path]
        return reply(params) if callable(reply) else reply


def _instant(value):
    return Response(
        {
            "status": "success",
            "data": {"result": [{"value": [0, str(value)]}], "stats": {"timings": {"evalTotalTime": 0.0123}}},
        }
    )


def _client(routes):
    return PrometheusClient("http://prom:9090", Session(routes))  # type: ignore[arg-type]


def test_scalar_returns_the_value_or_the_default():
    client = _client({"/api/v1/query": _instant(41943040)})
    assert client.scalar("x") == 41943040
    empty = _client({"/api/v1/query": Response({"status": "success", "data": {"result": []}})})
    assert empty.scalar("x", default=-1) == -1


def test_head_series_and_memory_use_the_lesson_queries():
    session = Session({"/api/v1/query": _instant(1842)})
    client = PrometheusClient("http://prom:9090", session)  # type: ignore[arg-type]
    assert client.head_series() == 1842
    assert client.resident_memory_bytes() == 1842
    assert [call[1]["query"] for call in session.calls] == [
        "prometheus_tsdb_head_series",
        'process_resident_memory_bytes{job="prometheus"}',
    ]


def test_tsdb_status_lists_the_offender_first():
    body = {
        "status": "success",
        "data": {
            "seriesCountByMetricName": [{"name": "request_latency_seconds_bucket", "value": 350000}],
            "labelValueCountByLabelName": [{"name": "user_id", "value": 49000}, {"name": "status", "value": 3}],
        },
    }
    status = _client({"/api/v1/status/tsdb": Response(body)}).tsdb_status()
    assert status.top_label == ("user_id", 49000)
    assert status.top_metric == ("request_latency_seconds_bucket", 350000)


def test_timed_query_reports_the_engine_time_and_the_row_count():
    timing = _client({"/api/v1/query": _instant(1)}).timed_query(runs=2)
    assert timing.engine_milliseconds == pytest.approx(12.3)
    assert timing.result_rows == 1
    assert timing.wall_milliseconds >= 0


def test_errors_become_prometheus_error():
    with pytest.raises(PrometheusError, match="503"):
        _client({"/api/v1/query": Response({}, status=503)}).scalar("x")
    with pytest.raises(PrometheusError, match="failed"):
        _client({"/api/v1/query": Response({"status": "error"})}).scalar("x")


def test_wait_for_scrapes_returns_once_the_count_has_grown():
    counts = iter([10, 10, 11, 12])
    client = _client({"/api/v1/query": lambda params: _instant(next(counts))})
    client.wait_for_scrapes("checkout", scrapes=2, timeout_seconds=30)
