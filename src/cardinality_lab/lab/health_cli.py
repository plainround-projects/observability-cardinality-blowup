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
