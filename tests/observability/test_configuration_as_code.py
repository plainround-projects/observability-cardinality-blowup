"""Lint the files that configure the stack: compose, the Collector, both Prometheus configs, rules and dashboard."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY = ROOT / "observability"
DATASOURCE_UIDS = {"prometheus", "tempo"}


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return dict(_yaml(ROOT / "docker-compose.yml"))


def test_every_third_party_image_is_pinned_to_a_version(compose):
    images = [service["image"] for service in compose["services"].values() if "build" not in service]
    assert len(images) >= 4
    for image in images:
        assert ":" in image
        assert not image.endswith(":latest")


def test_the_base_image_is_pinned_by_digest():
    first_line = next(line for line in (ROOT / "Dockerfile").read_text().splitlines() if line.startswith("FROM"))
    assert re.search(r"@sha256:[0-9a-f]{64}$", first_line)


def test_every_published_port_is_bound_to_loopback(compose):
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} on every interface"


def test_every_variable_the_compose_file_reads_is_in_env_example():
    used = set(re.findall(r"\$\{([A-Z_]+)", (ROOT / "docker-compose.yml").read_text()))
    declared = {line.split("=", 1)[0] for line in (ROOT / ".env.example").read_text().splitlines() if "=" in line}
    assert used <= declared, sorted(used - declared)


def test_the_app_runs_as_a_non_root_user_with_a_health_check_and_prometheus_has_a_memory_cap(compose):
    assert re.search(r"^USER app$", (ROOT / "Dockerfile").read_text(), re.MULTILINE)
    assert "healthcheck" in compose["services"]["app"]
    assert compose["services"]["prometheus"]["mem_limit"] == "3g"


def test_the_composed_defaults_are_the_safe_baseline(compose):
    environment = compose["services"]["app"]["environment"]
    assert environment["METRICS_INCLUDE_USER_ID"] == "${METRICS_INCLUDE_USER_ID:-false}"
    assert environment["SLOW_TENANT"] == "${SLOW_TENANT:-}"


def test_the_collector_traces_pipeline_has_the_memory_limiter_first_and_batch_last():
    config = _yaml(OBSERVABILITY / "collector" / "config.yaml")
    pipeline = config["service"]["pipelines"]["traces"]
    assert pipeline["processors"][0] == "memory_limiter"
    assert pipeline["processors"][-1] == "batch"
    assert all(name in config["exporters"] for name in pipeline["exporters"])


def test_the_guarded_config_differs_from_the_baseline_only_by_the_label_drop_rule():
    base = _yaml(OBSERVABILITY / "prometheus" / "prometheus.yml")
    guarded = _yaml(OBSERVABILITY / "prometheus" / "prometheus.guarded.yml")
    stripped = copy.deepcopy(guarded)
    for job in stripped["scrape_configs"]:
        job.pop("metric_relabel_configs", None)
    assert stripped == base
    checkout = next(job for job in guarded["scrape_configs"] if job["job_name"] == "checkout")
    assert checkout["metric_relabel_configs"] == [{"action": "labeldrop", "regex": "user_id"}]
    assert not any("metric_relabel_configs" in job for job in base["scrape_configs"])


def test_both_configs_load_the_rules_and_scrape_the_app_and_prometheus_itself():
    for name in ("prometheus.yml", "prometheus.guarded.yml"):
        config = _yaml(OBSERVABILITY / "prometheus" / name)
        assert config["rule_files"] == ["/etc/prometheus/rules/*.rules.yml"]
        assert {job["job_name"] for job in config["scrape_configs"]} == {"checkout", "prometheus"}


def test_every_alert_has_a_severity_a_summary_and_a_runbook():
    for path in (OBSERVABILITY / "prometheus" / "rules").glob("*.rules.yml"):
        for group in _yaml(path)["groups"]:
            for rule in group["rules"]:
                assert rule["labels"]["severity"] in {"page", "ticket"}, rule["alert"]
                assert {"summary", "runbook"} <= set(rule["annotations"]), rule["alert"]


@pytest.fixture(scope="module")
def dashboard() -> dict[str, Any]:
    return dict(json.loads((OBSERVABILITY / "grafana" / "dashboards" / "cardinality-blowup.json").read_text()))


def test_dashboard_panel_ids_are_unique_and_every_target_uses_a_provisioned_datasource(dashboard):
    sources = _yaml(OBSERVABILITY / "grafana" / "provisioning" / "datasources" / "datasources.yaml")["datasources"]
    assert {source["uid"] for source in sources} == DATASOURCE_UIDS
    panels = dashboard["panels"]
    assert len({panel["id"] for panel in panels}) == len(panels)
    for panel in panels:
        assert panel["title"]
        assert panel["datasource"]["uid"] in DATASOURCE_UIDS
        assert all(target["datasource"]["uid"] in DATASOURCE_UIDS for target in panel["targets"])


def test_dashboard_shows_the_lessons_three_numbers_and_the_trace_search(dashboard):
    text = json.dumps(dashboard)
    for expected in (
        "prometheus_tsdb_head_series",
        "process_resident_memory_bytes",
        "prometheus_engine_query_duration",
        "traceql",
    ):
        assert expected in text


def test_the_placement_guide_gives_a_bounded_values_rule_and_an_example_for_each_kind():
    guide = (ROOT / "docs" / "label-placement-guide.md").read_text().lower()
    for expected in ("bounded", "metric label", "span attribute", "logs only", "route", "user.id", "stack trace"):
        assert expected in guide, expected
