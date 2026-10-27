from collections import Counter
from pathlib import Path

from cardinality_lab.lab.compose import BASE_CONFIG, GUARDED_CONFIG, Compose
from cardinality_lab.lab.load import LoadResult
from cardinality_lab.lab.prometheus import Measurement, QueryTiming, TsdbStatus
from cardinality_lab.lab.scenario import SLOW_TENANT, ScenarioPlan, ScenarioRunner, render_report
from cardinality_lab.lab.tempo import TraceHit


class FakePrometheus:
    def __init__(self):
        self.series = iter([1842, 198340, 1849, 1851])

    def wait_for_scrapes(self, job, scrapes=2, timeout_seconds=180.0):
        pass

    def measure(self, job):
        return Measurement(next(self.series), 41_943_040, QueryTiming(8.0, 5.0, 1), 70)

    def tsdb_status(self):
        return TsdbStatus((("request_latency_seconds_bucket", 350000),), (("user_id", 49000), ("status", 3)))

    def scalar(self, expression, default=0.0):
        return 0.0475


class FakeTempo:
    def __init__(self):
        self.searches = []

    def search_by_tags(self, tags, start, end, limit=1000):
        return [TraceHit(f"{i:032x}", 5.0, "GET /checkout") for i in range(3)]

    def search_traceql(self, query, start, end, limit=1000):
        return [TraceHit(f"{i:032x}", 2010.0, "GET /checkout") for i in range(5)]

    def wait_for_search(self, search, expected_at_least, timeout_seconds=90.0):
        return search()


def _fake_load(plan):
    users = Counter({"user-000007": 3, "user-000008": 1})
    tenants = Counter({SLOW_TENANT: 5, "tenant-0001": 95})
    return LoadResult(plan.requests, Counter({200: plan.requests}), users, tenants, 1000.0, 1010.0)


def test_the_phases_run_in_the_lessons_order_with_the_right_settings():
    calls = []
    compose = Compose(Path("."), {}, runner=lambda command, env, cwd: calls.append((command[2:4], dict(env))))
    plan = ScenarioPlan("http://app", users=50_000, requests=40_000, slow_phase_requests=100)
    log: list[str] = []
    report = ScenarioRunner(plan, compose, FakePrometheus(), FakeTempo(), load=_fake_load, log=log.append).run()

    includes = [env["METRICS_INCLUDE_USER_ID"] for command, env in calls if command == ["up", "-d"]]
    assert includes.count("true") == 2
    assert includes[:3] == ["false", "false", "true"]
    assert [line[0] for line in log if line[:1].isdigit()] == ["1", "2", "3", "4", "5", "6"]
    configs = [env["PROMETHEUS_CONFIG"] for _, env in calls]
    assert configs[0] == BASE_CONFIG
    assert GUARDED_CONFIG in configs
    slow_envs = {env["SLOW_TENANT"] for _, env in calls if env["SLOW_TENANT"]}
    assert slow_envs == {SLOW_TENANT}

    assert report.series_growth == 198340 / 1842
    assert report.diagnosis.top_label == ("user_id", 49000)
    assert (report.probe_user, report.probe_user_requests, report.probe_user_traces) == ("user-000007", 3, 3)
    assert report.slow.traces_found == 5
    assert report.slow.expected_slow_requests == 5
    assert report.slow.shortest_slow_span_seconds == 2.01


def test_the_report_prints_every_number_the_lesson_asks_for():
    compose = Compose(Path("."), {}, runner=lambda *args: None)
    plan = ScenarioPlan("http://app", users=50_000, requests=40_000, slow_phase_requests=100)
    text = render_report(
        ScenarioRunner(plan, compose, FakePrometheus(), FakeTempo(), load=_fake_load, log=lambda _: None).run()
    )
    for expected in ["baseline", "with user_id", "after the fix", "guarded", "user_id", "49000", "tenant-0007", "p95"]:
        assert expected in text
    assert "1842" in text
    assert "198340" in text


def test_compose_commands_pass_the_overrides_and_failures_carry_the_output(tmp_path):
    import pytest

    from cardinality_lab.lab.compose import ComposeError, run_command

    seen = []
    compose = Compose(
        tmp_path, {"KEEP": "1"}, runner=lambda command, env, cwd: seen.append((list(command), dict(env), cwd))
    )
    compose.reset_prometheus(GUARDED_CONFIG)
    assert [entry[0][:3] for entry in seen] == [
        ["docker", "compose", "rm"],
        ["docker", "volume", "rm"],
        ["docker", "compose", "up"],
    ]
    assert all(entry[1]["KEEP"] == "1" for entry in seen)
    assert all(entry[2] == tmp_path for entry in seen)
    with pytest.raises(ComposeError, match="boom"):
        run_command(["sh", "-c", "echo boom >&2; exit 3"], {}, tmp_path)
