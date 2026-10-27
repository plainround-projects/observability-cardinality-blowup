"""Docker Compose control for the scenario: recreate the app with different settings, reset Prometheus."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

Runner = Callable[[Sequence[str], Mapping[str, str], Path], None]

PROJECT = "observability-cardinality-blowup"
PROMETHEUS_VOLUME = f"{PROJECT}_prometheus-data"
BASE_CONFIG = "./observability/prometheus/prometheus.yml"
GUARDED_CONFIG = "./observability/prometheus/prometheus.guarded.yml"


class ComposeError(RuntimeError):
    """A docker command failed."""


def run_command(command: Sequence[str], environment: Mapping[str, str], working_directory: Path) -> None:
    """Run a command, raising ``ComposeError`` with its output when it fails."""
    completed = subprocess.run(
        list(command),
        cwd=working_directory,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ComposeError(
            f"{' '.join(command)} failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr}"
        )


class Compose:
    """The few compose operations the scenario needs; the runner is injectable so tests need no Docker."""

    def __init__(
        self, project_directory: Path, base_environment: Mapping[str, str], runner: Runner = run_command
    ) -> None:
        """Take the folder holding docker-compose.yml, the environment to start from and a command runner."""
        self._directory = project_directory
        self._base = dict(base_environment)
        self._runner = runner

    def _run(self, command: Sequence[str], overrides: Mapping[str, str]) -> None:
        self._runner(command, {**self._base, **overrides}, self._directory)

    def recreate_app(self, include_user_id: bool, slow_tenant: str, prometheus_config: str) -> None:
        """Start the app with the given metric labels and slow tenant, and wait until it is healthy."""
        overrides = {
            "METRICS_INCLUDE_USER_ID": "true" if include_user_id else "false",
            "SLOW_TENANT": slow_tenant,
            "PROMETHEUS_CONFIG": prometheus_config,
        }
        self._run(["docker", "compose", "up", "-d", "--force-recreate", "--no-deps", "--wait", "app"], overrides)

    def reset_prometheus(self, prometheus_config: str, include_user_id: bool = False, slow_tenant: str = "") -> None:
        """Replace Prometheus with a fresh one (empty TSDB) that loads ``prometheus_config``.

        Prometheus keeps a series in its head for about two hours after the last sample, so the only quick way to see
        the post-fix steady state is a new instance.
        """
        overrides = {
            "PROMETHEUS_CONFIG": prometheus_config,
            "METRICS_INCLUDE_USER_ID": "true" if include_user_id else "false",
            "SLOW_TENANT": slow_tenant,
        }
        self._run(["docker", "compose", "rm", "-sf", "prometheus"], overrides)
        self._run(["docker", "volume", "rm", "-f", PROMETHEUS_VOLUME], overrides)
        self._run(["docker", "compose", "up", "-d", "--no-deps", "--wait", "prometheus"], overrides)
