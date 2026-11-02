# Python subprocess (running Docker commands from Python)

## What it is

`subprocess` is the standard-library module for starting other programs from Python. `subprocess.run(command, ...)` starts the program named by the first item of the list, waits for it to finish and returns a `CompletedProcess` object with the **return code** (the exit code), and, if asked, the captured output. A command is a **list** of strings (`["docker", "compose", "up"]`), not one string, so no shell is involved and nothing needs quoting.

## Why this repository uses it

The scenario must change the running stack between phases: restart the app with a different label setting and a different Prometheus configuration, and replace Prometheus with an empty one. The module `lab/compose.py` wraps those few `docker` commands. The command runner is a parameter, so the unit tests use a fake and need no Docker.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/cardinality_lab/lab/compose.py` | The three Docker operations and the function that runs them. |
| `src/cardinality_lab/lab/scenario.py` | Calls them at the start of each phase (see `python.md`). |
| `tests/unit/lab/test_scenario.py` | Tests them with a fake runner and with a real failing command. |

## How it works underneath

`subprocess.run` asks the operating system to start a new process. The arguments it passes:

- `cwd=` sets the working directory of the new process (here the folder with `docker-compose.yml`, so `docker compose` finds it).
- `env=` replaces the new process's environment variables. Docker Compose reads `${NAME}` placeholders from the environment, so overriding `METRICS_INCLUDE_USER_ID` or `PROMETHEUS_CONFIG` here changes how Compose starts the containers, with no edit to any file.
- `capture_output=True` collects standard output and standard error instead of printing them; `text=True` gives them as text instead of bytes.
- `check=False` means "do not raise on a non-zero return code"; the code checks `returncode` itself and raises its own error carrying the output.

## Walkthrough of this repository's use

```python
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
```

`Runner` is a **type alias**: a name for the type "a function that takes the command (a sequence of strings), the environment and the working directory, and returns nothing". The constants name the Compose project (so the volume's full name is `observability-cardinality-blowup_prometheus-data`) and the two Prometheus configuration files.

```python
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
```

`ComposeError` is the error this module raises. `run_command` is the real runner. It calls `subprocess.run` with the arguments above. When the return code is not 0, it raises `ComposeError` with the command line, the code, and what the command printed on both streams, so a failure in a long scenario explains itself.

```python
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
```

`Compose` stores the project folder, a copy of the base environment and the runner (default: the real one). `_run` merges the base environment with per-call overrides using `{**base, **overrides}` (later keys win) and calls the runner.

```python
    def recreate_app(self, include_user_id: bool, slow_tenant: str, prometheus_config: str) -> None:
        """Start the app with the given metric labels and slow tenant, and wait until it is healthy."""
        overrides = {
            "METRICS_INCLUDE_USER_ID": "true" if include_user_id else "false",
            "SLOW_TENANT": slow_tenant,
            "PROMETHEUS_CONFIG": prometheus_config,
        }
        self._run(["docker", "compose", "up", "-d", "--force-recreate", "--no-deps", "--wait", "app"], overrides)
```

`recreate_app` sets three variables (`METRICS_INCLUDE_USER_ID`, `SLOW_TENANT`, `PROMETHEUS_CONFIG`) and runs `docker compose up -d --force-recreate --no-deps --wait app`: `-d` runs in the background, `--force-recreate` replaces the container even if its configuration did not change, `--no-deps` leaves the other services alone, and `--wait` blocks until the app's health check passes.

```python
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
```

`reset_prometheus` replaces Prometheus with an empty one. The docstring gives the reason: Prometheus keeps a series in its "head" (the in-memory block of recent data) for about two hours after its last sample, so the only quick way to see the steady state after a fix is a new instance. Three commands: `docker compose rm -sf prometheus` (`-s` stops it, `-f` does not ask), `docker volume rm -f <project>_prometheus-data` (deletes the stored data; `-f` ignores a missing volume), and `docker compose up -d --no-deps --wait prometheus` (starts a fresh one with the chosen configuration file).

## Try it yourself

```bash
.venv/bin/python -c "
from cardinality_lab.lab.compose import run_command
from pathlib import Path
run_command(['sh', '-c', 'echo boom >&2; exit 3'], {}, Path('.'))" 2>&1 | tail -4
```

Expected: a `ComposeError` whose message contains `failed (3)` and `boom`.

```bash
.venv/bin/python -m pytest tests/unit/lab/test_scenario.py -q
```

Expected: `3 passed`; the first two tests use a fake runner, so no container starts.

```bash
.venv/bin/python -c "
from pathlib import Path
from cardinality_lab.lab.compose import Compose, GUARDED_CONFIG
Compose(Path('.'), {}, runner=lambda c, e, d: print(' '.join(c))).reset_prometheus(GUARDED_CONFIG)"
```

Expected: the three commands printed, not run.

```bash
docker volume ls | grep prometheus-data
```

Expected (while the stack is up): `observability-cardinality-blowup_prometheus-data`.

```bash
PROMETHEUS_CONFIG=./observability/prometheus/prometheus.guarded.yml docker compose config | grep -B1 -A1 prometheus.guarded
```

Expected: the resolved Compose file mounts the guarded file.

## Mistakes people make

- **Passing one string with `shell=True`.** Quoting errors and injection risks. A list avoids the shell.
- **Not checking the return code.** A silent failure in phase 1 would produce nonsense numbers in phase 6.
- **Dropping the output of a failing command.** The error here carries both streams.
- **Replacing the whole environment by accident.** `env=` replaces everything, which is why the base environment is copied in first.
- **Forgetting `--wait`.** The next phase would start sending traffic to an app that is not ready.

## Check yourself

1. Why is a command a list and not a string? *No shell is involved, so no quoting or injection problems.*
2. What does `check=False` do? *`run` does not raise on a non-zero code; the caller inspects it.*
3. Why is the runner injected? *So tests can fake it and need no Docker.*
4. How can the scenario change how Compose starts a service without editing a file? *By setting environment variables that the file reads with `${NAME}`.*
5. Why start a new Prometheus instead of waiting? *A series stays in the head about two hours after its last sample.*

## Further reading

- `subprocess`: https://docs.python.org/3.12/library/subprocess.html
- `docker compose up`: https://docs.docker.com/reference/cli/docker/compose/up/
- `docker compose rm`: https://docs.docker.com/reference/cli/docker/compose/rm/
- `docker volume rm`: https://docs.docker.com/reference/cli/docker/volume/rm/
