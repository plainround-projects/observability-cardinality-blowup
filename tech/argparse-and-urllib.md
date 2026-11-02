# argparse and urllib (standard library command-line tools)

## What it is

Two standard-library modules that the command-line tools of this repository are built on.

- `argparse` reads the **command-line arguments** a program was started with (for example `--users 50000 --requests 200000`), converts them to the right types, supplies defaults, and prints a help text for `--help`.
- `urllib.request` is a small HTTP client that comes with Python. `urllib.request.urlopen(url, timeout=5)` makes a GET request and returns a response you can use in a `with` block; `urllib.request.Request(url)` builds a request on which you can add headers first.

A program's **exit code** is the number it returns to the operating system when it ends: `0` for success, anything else for failure. `sys.exit(main())` passes the return value of `main()` to the system, so `make` and Docker can see success or failure.

## Why this repository uses it

Four small commands: the app's **health probe** (run by Docker as the container's health check), the **load** generator, the **scenario** and the **stack health** check. The health probe runs inside the slim image where nothing extra should be installed, so it uses `urllib`.

## Where it appears

| Path | What it is |
| --- | --- |
| `src/cardinality_lab/interfaces/health_cli.py` | `cardinality-lab-health`: probes one URL; the Docker health check. |
| `src/cardinality_lab/lab/load_cli.py` | `cardinality-lab-load`: sends traffic. |
| `src/cardinality_lab/lab/scenario_cli.py` | `cardinality-lab-scenario`: runs the six phases and prints the report. |
| `src/cardinality_lab/lab/health_cli.py` | The stack check run by `make health` (run with `python -m`, not installed as a command). |
| `pyproject.toml` | Maps each command name to its `main` function (see `pyproject-toml.md`). |

## How it works underneath

At start-up the operating system hands the program a list of strings (`sys.argv`). `argparse.ArgumentParser()` builds a parser; `add_argument("--users", type=int, default=50_000)` declares one option; `parse_args(argv)` reads the list, converts each value with `type`, and returns an object whose attributes are the values (`args.users`). On an error or `--help` it prints a message and exits. `parse_args(None)` reads `sys.argv`; a test passes an explicit list instead. The underscore in `50_000` is only a readability aid for humans; Python ignores it.

`urlopen` opens a TCP connection, sends `GET <path> HTTP/1.1` and waits up to `timeout` seconds for each step. A non-success status (such as 503) raises `urllib.error.HTTPError`, a subclass of `URLError`. A refused or timed-out connection raises `URLError` or `TimeoutError`; both derive from `OSError`.

**HTTP basic authentication** sends the header `Authorization: Basic <token>` where the token is `username:password` encoded in base64. Base64 is an encoding, not encryption: anyone who sees the header can decode it, so it is only for traffic on a trusted network such as `127.0.0.1`.

## Walkthrough of this repository's use

### `interfaces/health_cli.py`: the container health probe

```python
"""``cardinality-lab-health``: exit 0 when /healthz answers 200; used by the Docker health check."""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request


def main(argv: list[str] | None = None) -> int:
    """Probe the URL and return the process exit code."""
    parser = argparse.ArgumentParser(description="Probe the app's health endpoint.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    try:
        with urllib.request.urlopen(args.url, timeout=args.timeout) as response:
            return 0 if response.status == 200 else 1
    except (urllib.error.URLError, TimeoutError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

All imports are standard library. `main(argv=None) -> int` returns the exit code instead of exiting itself, which makes it testable. `--url` is required; `--timeout` is a float with default 5.0. `with urllib.request.urlopen(args.url, timeout=args.timeout) as response:` makes the request and closes it afterwards. `return 0 if response.status == 200 else 1` is the decision: only a 200 answer is healthy. Any network error (`URLError`, `TimeoutError`, `OSError`) means unhealthy, exit code 1, with no traceback. The last two lines run `main()` only when the file is executed as a program and pass its return value to `sys.exit`. In `docker-compose.yml` the health check is `cardinality-lab-health --url http://localhost:8080/healthz --timeout 10` (see `docker-compose.md`).

### `lab/load_cli.py`: send traffic

```python
"""``cardinality-lab-load``: send simulated traffic from many users to the checkout app."""

from __future__ import annotations

import argparse
import os
import sys

from cardinality_lab.lab.load import LoadPlan, run_load


def main(argv: list[str] | None = None) -> int:
    """Run the load and print a one-line summary; exit 1 when any request failed."""
    parser = argparse.ArgumentParser(description="Send simulated traffic to the checkout app.")
    parser.add_argument("--users", type=int, default=50_000)
    parser.add_argument("--requests", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '28082')}")
    args = parser.parse_args(argv)
    result = run_load(LoadPlan(args.url, args.users, args.requests, args.seed, args.concurrency))
    print(
        f"sent {result.sent} requests from {result.distinct_users} distinct users "
        f"at {result.requests_per_second:.0f}/s; statuses {dict(sorted(result.statuses.items()))}"
    )
    return 1 if result.statuses.get(0) or any(s >= 500 and s != 502 for s in result.statuses) else 0


if __name__ == "__main__":
    sys.exit(main())
```

Options: `--users` (default 50,000, the number of distinct simulated users), `--requests` (200,000), `--seed` (2026), `--concurrency` (32 workers) and `--url` (default: the app's published port from the `APP_HOST_PORT` variable, else 28082; `os.environ.get(name, default)` reads an environment variable with a fallback). It runs the load and prints one line: how many were sent, how many distinct users appeared, the rate, and the status codes seen (`dict(sorted(result.statuses.items()))` turns the counter into a sorted dictionary for printing). The exit code is 1 when any request got no answer (status 0) or any 5xx status other than 502 appeared. The 502 is excluded because it is the simulated gateway error and expected in the traffic.

### `lab/scenario_cli.py`: run the experiment

```python
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
        PrometheusClient(f"http://127.0.0.1:{env.get('PROMETHEUS_HOST_PORT', '29090')}"),
        TempoClient(f"http://127.0.0.1:{env.get('TEMPO_HOST_PORT', '23200')}"),
    )
    print(render_report(runner.run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The options are the experiment's size (users, requests, seed). It builds the plan with the app's URL, creates the runner with the real collaborators (`Compose(Path.cwd(), env)` controls Docker in the current folder; the Prometheus and Tempo clients use the published ports), and prints `render_report(runner.run())`. `Path.cwd()` is the current directory, which is the repository folder when started from `make run`. It returns 0 when the run completes; a failed assertion in a phase raises an error instead.

### `lab/health_cli.py`: the stack check

```python
"""``cardinality-lab-health``-style stack check: the app, Prometheus, Tempo and Grafana all answer."""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

from cardinality_lab.lab.prometheus import PrometheusClient
from cardinality_lab.lab.tempo import TempoClient


def _http_ok(url: str, auth: tuple[str, str] | None = None) -> bool:
    request = urllib.request.Request(url)
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main() -> int:
    """Print one line per check and exit 1 when any fails."""
    env = os.environ
    checks = [
        ("app /healthz", _http_ok(f"http://127.0.0.1:{env.get('APP_HOST_PORT', '28082')}/healthz")),
        (
            "prometheus /-/healthy",
            PrometheusClient(f"http://127.0.0.1:{env.get('PROMETHEUS_HOST_PORT', '29090')}").ready(),
        ),
        ("tempo /ready", TempoClient(f"http://127.0.0.1:{env.get('TEMPO_HOST_PORT', '23200')}").ready()),
        (
            "grafana queries prometheus",
            _http_ok(
                f"http://127.0.0.1:{env.get('GRAFANA_HOST_PORT', '23000')}/api/datasources/uid/prometheus/health",
                ("admin", env.get("GRAFANA_ADMIN_PASSWORD", "")),
            ),
        ),
        (
            "grafana queries tempo",
            _http_ok(
                f"http://127.0.0.1:{env.get('GRAFANA_HOST_PORT', '23000')}"
                "/api/datasources/proxy/uid/tempo/api/search?limit=1",
                ("admin", env.get("GRAFANA_ADMIN_PASSWORD", "")),
            ),
        ),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
```

`_http_ok(url, auth=None)` builds a `Request`; when credentials are given it computes the basic-authentication token (`base64.b64encode(f"{user}:{password}".encode()).decode()`: encode the text to bytes, base64 it, decode the result back to text) and adds the header. The function-level `import base64` is used only here. `main` lists five checks: the app's `/healthz`, Prometheus `/-/healthy`, Tempo `/ready`, and Grafana asked to query Prometheus and Tempo. Grafana's health check for Tempo does not exist in version 11.2, so the Tempo check sends a real search through Grafana's proxy path `/api/datasources/proxy/uid/tempo/api/search?limit=1`. Each result is printed as `ok   name` or `FAIL name`; the exit code is 0 only if all pass. `make up` ends by running it.

## Try it yourself

```bash
.venv/bin/cardinality-lab-load --help
```

Expected: usage and the five options with defaults.

```bash
.venv/bin/cardinality-lab-health --url http://127.0.0.1:9/healthz --timeout 1; echo "exit code $?"
```

Expected: `exit code 1`.

```bash
.venv/bin/cardinality-lab-health --url http://127.0.0.1:28082/healthz; echo "exit code $?"
```

Expected (needs `make up`): `exit code 0`.

```bash
.venv/bin/python -c "import base64; print(base64.b64encode(b'admin:secret').decode())"
```

Expected: `YWRtaW46c2VjcmV0`, which decodes straight back to `admin:secret`: base64 hides nothing.

```bash
make health
```

Expected after `make up`: five lines starting with `ok`.

## Mistakes people make

- **Calling `sys.exit` deep inside a function.** Hard to test. Here only the last two lines exit.
- **Ignoring the exit code** of a health probe: Docker looks at it.
- **No timeout on `urlopen`.** It waits forever. Every call here sets one.
- **Sending credentials over a network you do not control.** Basic authentication is readable by anyone who sees the traffic; here it goes to `127.0.0.1` only.
- **Treating "no error" as healthy.** A `204` or `301` is not `200`; the probe asks for exactly 200.

## Check yourself

1. What does `parse_args(argv)` return? *An object whose attributes are the option values, converted to their declared types.*
2. What exit code tells Docker the container is unhealthy? *Any non-zero code; here 1.*
3. Why does the probe use `urllib` and not `requests`? *It is in the standard library, so the image needs nothing extra.*
4. Why is a 502 not counted as a failure by the load command? *It is the simulated gateway error and part of the normal traffic.*
5. Is base64 encryption? *No. It is a reversible encoding; anyone can decode it.*

## Further reading

- `argparse`: https://docs.python.org/3.12/library/argparse.html
- `urllib.request`: https://docs.python.org/3.12/library/urllib.request.html
- `base64`: https://docs.python.org/3.12/library/base64.html
- `sys.exit`: https://docs.python.org/3.12/library/sys.html#sys.exit
- HTTP authentication (basic scheme): https://developer.mozilla.org/en-US/docs/Web/HTTP/Authentication
