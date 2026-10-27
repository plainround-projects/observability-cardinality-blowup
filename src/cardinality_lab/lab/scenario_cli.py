"""``cardinality-lab-scenario``: run the six phases and print the report."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cardinality_lab.lab.compose import Compose
from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.scenario import ScenarioPlan, ScenarioRunner, render_report
from cardinality_lab.lab.tempo import TempoClient


def main(argv: list[str] | None = None) -> int:
    """Run the scenario against the stack that ``make up`` started."""
    parser = argparse.ArgumentParser(description="Overload Prometheus with a user_id label, find it, fix it.")
    parser.add_argument("--users", type=int, default=50_000)
    parser.add_argument("--requests", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args(argv)
    env = os.environ
    plan = ScenarioPlan(f"http://127.0.0.1:{env.get('APP_HOST_PORT', '28082')}", args.users, args.requests, args.seed)
    runner = ScenarioRunner(
        plan,
        Compose(Path.cwd(), env),
        PrometheusClient(f"http://127.0.0.1:{env.get('PROMETHEUS_HOST_PORT', '9090')}"),
        TempoClient(f"http://127.0.0.1:{env.get('TEMPO_HOST_PORT', '3200')}"),
    )
    print(render_report(runner.run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
