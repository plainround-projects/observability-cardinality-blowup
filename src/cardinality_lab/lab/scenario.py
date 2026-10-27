"""The lesson's six steps as one repeatable run: baseline, blow-up, diagnosis, fix, guard, hidden slow dependency."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from cardinality_lab.domain.series import SeriesEstimate, expected_series
from cardinality_lab.infrastructure.prometheus_metrics import LATENCY_BUCKETS
from cardinality_lab.lab.compose import BASE_CONFIG, GUARDED_CONFIG, Compose
from cardinality_lab.lab.load import LoadPlan, LoadResult, run_load, tenant_name, user_name
from cardinality_lab.lab.prometheus import Measurement, TsdbStatus
from cardinality_lab.lab.tempo import TraceHit

JOB = "checkout"
SLOW_TENANT = tenant_name(7)
STATUS_VALUES = 3
P95_SLOW_FLOOR_SECONDS = 2.0


class MetricsStore(Protocol):
    """The Prometheus calls the scenario makes."""

    def wait_for_scrapes(self, job: str, scrapes: int = ..., timeout_seconds: float = ...) -> None:
        """Block until the job has been scraped again."""
        ...

    def measure(self, job: str) -> Measurement:
        """The lesson's three numbers now."""
        ...

    def tsdb_status(self) -> TsdbStatus:
        """The backend's own statistics."""
        ...

    def scalar(self, expression: str, default: float = ...) -> float:
        """One value of an instant query."""
        ...


class TraceStore(Protocol):
    """The Tempo calls the scenario makes."""

    def search_by_tags(self, tags: Mapping[str, str], start: float, end: float, limit: int = ...) -> list[TraceHit]:
        """Traces with every tag."""
        ...

    def search_traceql(self, query: str, start: float, end: float, limit: int = ...) -> list[TraceHit]:
        """Traces matching a TraceQL query."""
        ...

    def wait_for_search(
        self, search: Callable[[], list[TraceHit]], expected_at_least: int, timeout_seconds: float = ...
    ) -> list[TraceHit]:
        """Poll until the search returns enough hits."""
        ...


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    """How big to run the experiment."""

    app_url: str
    users: int
    requests: int
    seed: int = 2026
    warmup_requests: int = 5_000
    slow_phase_requests: int = 8_000


@dataclass(frozen=True, slots=True)
class SlowFinding:
    """What the hidden slow dependency looked like in metrics and in traces."""

    route_p95_before_seconds: float
    route_p95_after_seconds: float
    tenant_share: float
    traces_found: int
    shortest_slow_span_seconds: float
    expected_slow_requests: int


@dataclass(frozen=True, slots=True)
class Report:
    """Every number the lesson asks for, from one run."""

    plan: ScenarioPlan
    expected: SeriesEstimate
    baseline: Measurement
    blown_up: Measurement
    distinct_users: int
    diagnosis: TsdbStatus
    fixed: Measurement
    probe_user: str
    probe_user_requests: int
    probe_user_traces: int
    guarded: Measurement
    slow: SlowFinding

    @property
    def series_growth(self) -> float:
        """How many times more series the blow-up created."""
        return self.blown_up.head_series / max(self.baseline.head_series, 1)


class ScenarioRunner:
    """Runs the phases in order against the stack, using injected collaborators."""

    def __init__(
        self,
        plan: ScenarioPlan,
        compose: Compose,
        prometheus: MetricsStore,
        tempo: TraceStore,
        load: Callable[[LoadPlan], LoadResult] = run_load,
        log: Callable[[str], None] = print,
    ) -> None:
        """Take the plan and the collaborators."""
        self._plan = plan
        self._compose = compose
        self._prometheus = prometheus
        self._tempo = tempo
        self._load = load
        self._log = log

    def _traffic(self, requests: int, seed_offset: int) -> LoadResult:
        plan = self._plan
        result = self._load(LoadPlan(plan.app_url, plan.users, requests, plan.seed + seed_offset))
        self._log(
            f"  sent {result.sent} requests from {result.distinct_users} users at {result.requests_per_second:.0f}/s"
        )
        return result

    def _settle(self) -> None:
        self._prometheus.wait_for_scrapes(JOB, scrapes=2)

    def run(self) -> Report:
        """Run every phase and return the report."""
        plan = self._plan
        self._log("1. Baseline: fresh Prometheus, three bounded labels")
        self._compose.reset_prometheus(BASE_CONFIG)
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=BASE_CONFIG)
        self._traffic(plan.warmup_requests, 0)
        self._settle()
        baseline = self._prometheus.measure(JOB)
        expected = expected_series(
            {"route": 1, "method": 1, "status": STATUS_VALUES}, finite_buckets=len(LATENCY_BUCKETS)
        )

        self._log("2. Blow it up: add the user_id label to both metrics and send the full traffic")
        self._compose.recreate_app(include_user_id=True, slow_tenant="", prometheus_config=BASE_CONFIG)
        blast = self._traffic(plan.requests, 1)
        self._settle()
        blown_up = self._prometheus.measure(JOB)

        self._log("3. Find the offender from Prometheus's own statistics")
        diagnosis = self._prometheus.tsdb_status()

        self._log("4. Fix: remove the label, keep user.id on the span, start from a fresh Prometheus with the guard")
        self._compose.reset_prometheus(GUARDED_CONFIG)
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        fix_load = self._traffic(plan.requests // 4, 2)
        self._settle()
        fixed = self._prometheus.measure(JOB)
        probe_user, probe_requests = fix_load.requests_per_user.most_common(1)[0]
        hits = self._tempo.wait_for_search(
            lambda: self._tempo.search_by_tags(
                {"user.id": probe_user}, fix_load.started_at - 5, fix_load.finished_at + 30
            ),
            expected_at_least=probe_requests,
        )

        self._log("5. Guard: someone adds user_id back; the scrape rule drops it before storage")
        self._compose.recreate_app(include_user_id=True, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        self._traffic(plan.requests // 4, 3)
        self._settle()
        guarded = self._prometheus.measure(JOB)

        self._log("6. Hidden slow dependency: one route, one tenant, found from traces")
        slow = self._slow_dependency()
        return Report(
            plan=plan,
            expected=expected,
            baseline=baseline,
            blown_up=blown_up,
            distinct_users=blast.distinct_users,
            diagnosis=diagnosis,
            fixed=fixed,
            probe_user=probe_user,
            probe_user_requests=probe_requests,
            probe_user_traces=len(hits),
            guarded=guarded,
            slow=slow,
        )

    def _route_p95(self, window_seconds: float) -> float:
        expression = (
            "histogram_quantile(0.95, sum by (le) "
            f'(increase(request_latency_seconds_bucket{{job="{JOB}"}}[{int(window_seconds)}s])))'
        )
        return self._prometheus.scalar(expression)

    def _slow_dependency(self) -> SlowFinding:
        plan = self._plan
        self._compose.recreate_app(include_user_id=False, slow_tenant="", prometheus_config=GUARDED_CONFIG)
        before_load = self._traffic(plan.slow_phase_requests, 4)
        self._settle()
        before = self._route_p95(before_load.finished_at - before_load.started_at + 45)

        self._compose.recreate_app(include_user_id=False, slow_tenant=SLOW_TENANT, prometheus_config=GUARDED_CONFIG)
        after_load = self._traffic(plan.slow_phase_requests, 5)
        self._settle()
        after = self._route_p95(after_load.finished_at - after_load.started_at + 45)

        expected_slow = after_load.requests_per_tenant[SLOW_TENANT]
        query = (
            f'{{ name = "checkout" && span.tenant.id = "{SLOW_TENANT}" && span.route = "checkout" && duration > 1s }}'
        )
        hits = self._tempo.wait_for_search(
            lambda: self._tempo.search_traceql(query, after_load.started_at - 5, after_load.finished_at + 30),
            expected_at_least=expected_slow,
        )
        return SlowFinding(
            route_p95_before_seconds=before,
            route_p95_after_seconds=after,
            tenant_share=expected_slow / max(after_load.sent, 1),
            traces_found=len(hits),
            shortest_slow_span_seconds=min((hit.duration_ms for hit in hits), default=0.0) / 1000,
            expected_slow_requests=expected_slow,
        )


def render_report(report: Report) -> str:
    """The run as the table the README quotes."""
    base, blown, fixed, guarded = report.baseline, report.blown_up, report.fixed, report.guarded
    label, label_values = report.diagnosis.top_label
    metric, metric_series = report.diagnosis.top_metric
    slow = report.slow
    lines = [
        f"Plan: {report.plan.users} users, {report.plan.requests} requests",
        "",
        f"Expected series for the app (1 route x 1 method x {STATUS_VALUES} statuses): "
        f"counter {report.expected.counter_series}, histogram {report.expected.histogram_series}, "
        f"total {report.expected.total}",
        "",
        f"{'':28}{'series':>10}{'memory MB':>12}{'query ms':>10}{'samples/scrape':>16}",
        _row("baseline", base),
        _row("with user_id", blown),
        _row("after the fix (fresh TSDB)", fixed),
        _row("user_id re-added, guarded", guarded),
        f"series growth with user_id: {report.series_growth:.0f}x "
        f"({report.distinct_users} distinct users in the traffic)",
        "",
        f"Offender from /api/v1/status/tsdb: label '{label}' has {label_values} values; "
        f"metric '{metric}' has {metric_series} series.",
        f"Traces for {report.probe_user}: {report.probe_user_traces} found, "
        f"{report.probe_user_requests} requests sent.",
        "",
        f"Hidden slow dependency ({SLOW_TENANT}, {slow.tenant_share:.2%} of traffic): "
        f"route p95 {slow.route_p95_before_seconds * 1000:.1f} ms -> {slow.route_p95_after_seconds * 1000:.1f} ms.",
        f"Trace query on tenant + route + duration > 1 s: {slow.traces_found} traces of {slow.expected_slow_requests} "
        f"slow requests, shortest {slow.shortest_slow_span_seconds * 1000:.0f} ms.",
    ]
    return "\n".join(lines)


def _row(name: str, measurement: Measurement) -> str:
    return (
        f"{name:28}{measurement.head_series:>10}{measurement.memory_megabytes:>12.0f}"
        f"{measurement.query.wall_milliseconds:>10.0f}{measurement.samples_per_scrape:>16}"
    )


__all__ = [
    "JOB",
    "SLOW_TENANT",
    "Report",
    "ScenarioPlan",
    "ScenarioRunner",
    "SlowFinding",
    "TraceHit",
    "render_report",
    "user_name",
]
