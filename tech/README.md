# Technology notes

These notes teach every technology used in `observability-cardinality-blowup`, from zero, through this repository's own files. They assume you have never used any of them. Every source file, configuration file, dashboard, alert rule, compose file and Makefile line in the repository is quoted and explained in one of them. Each note has the same nine parts: what it is, why this repository uses it, where it appears, how it works underneath, a walkthrough of the repository's use, commands to try, common mistakes, five questions to check yourself, and links to the official documentation for the pinned version.

## If you have ten minutes

Read these three, in this order:

1. [prometheus-client.md](prometheus-client.md): what a label does to the number of series, and the switch that makes the lesson's mistake.
2. [prometheus.md](prometheus.md): how Prometheus stores series, how to find the offender, and how the scrape guard fixes it for good.
3. [tempo.md](tempo.md): where the per-user detail goes instead, and how a TraceQL query finds the slow tenant.

## Reading order

**The language and its standard library**

1. [python.md](python.md): the language, the layered design, the series arithmetic, the use case and the six-phase scenario.
2. [python-logging.md](python-logging.md): JSON log lines with trace ids.
3. [python-threads-and-signals.md](python-threads-and-signals.md): the load generator and clean shutdown.
4. [python-subprocess.md](python-subprocess.md): how the scenario restarts containers.
5. [argparse-and-urllib.md](argparse-and-urllib.md): the command-line tools and the health probe.

**Web libraries and the protocol**

6. [http.md](http.md): the protocol everything speaks.
7. [flask.md](flask.md): the web application.
8. [waitress.md](waitress.md): the server that runs it.
9. [requests.md](requests.md): the load and store clients.

**Metrics, traces and dashboards**

10. [prometheus-client.md](prometheus-client.md): exposing metrics, and the mistake.
11. [opentelemetry.md](opentelemetry.md): spans that carry the user id.
12. [opentelemetry-collector.md](opentelemetry-collector.md): the trace pipeline.
13. [prometheus.md](prometheus.md) and [promql.md](promql.md): storage, the guard, rules and queries.
14. [tempo.md](tempo.md): trace storage and search.
15. [grafana.md](grafana.md): provisioning and the dashboard.

**Running everything**

16. [docker.md](docker.md): the image.
17. [docker-compose.md](docker-compose.md): the stack.
18. [make.md](make.md): the commands you type.
19. [bash.md](bash.md): the shell commands inside them.
20. [dotenv.md](dotenv.md): the `.env` files.

**Tests and quality**

21. [pytest.md](pytest.md): all tests and coverage.
22. [ruff.md](ruff.md), [mypy.md](mypy.md), [import-linter.md](import-linter.md): lint, types, layers.
23. [uv-and-lock-files.md](uv-and-lock-files.md): locked dependencies and the audit.
24. [pyproject-toml.md](pyproject-toml.md): packaging and tool settings.
25. [github-actions.md](github-actions.md): CI.

**File formats and housekeeping**

26. [yaml.md](yaml.md) and [json.md](json.md).
27. [git-and-editorconfig.md](git-and-editorconfig.md).

## The files and their roles

| File | Role |
| --- | --- |
| [python.md](python.md) | Python 3.12: domain, application, settings and the scenario. |
| [python-logging.md](python-logging.md) | The standard `logging` module and the JSON formatter. |
| [python-threads-and-signals.md](python-threads-and-signals.md) | Threads, locks, thread-local sessions, signals and clocks in the load generator and the shutdown handler. |
| [python-subprocess.md](python-subprocess.md) | `subprocess` and the Docker control the scenario uses. |
| [argparse-and-urllib.md](argparse-and-urllib.md) | The four command-line tools and the container health probe. |
| [http.md](http.md) | HTTP methods, headers, statuses and timeouts. |
| [flask.md](flask.md) | The checkout web application. |
| [waitress.md](waitress.md) | The production WSGI server. |
| [requests.md](requests.md) | The Prometheus and Tempo clients. |
| [prometheus-client.md](prometheus-client.md) | The metrics library and the switchable mistake. |
| [opentelemetry.md](opentelemetry.md) | The `checkout` and `payment.charge` spans and the `OTEL_*` settings. |
| [opentelemetry-collector.md](opentelemetry-collector.md) | The traces-only Collector configuration. |
| [prometheus.md](prometheus.md) | The two configurations, the guard, the alerts and the promtool tests. |
| [promql.md](promql.md) | Every PromQL expression in the repository. |
| [tempo.md](tempo.md) | Tempo configuration, tag search and TraceQL. |
| [grafana.md](grafana.md) | Data sources and the ten-panel dashboard. |
| [docker.md](docker.md) | The Dockerfile (cache mounts, digest pin, non-root user) and `.dockerignore`. |
| [docker-compose.md](docker-compose.md) | The Compose file, key by key. |
| [make.md](make.md) | The Makefile, target by target. |
| [bash.md](bash.md) | The shell in Makefile recipes, health checks and CI. |
| [dotenv.md](dotenv.md) | `.env` and `.env.example`. |
| [pytest.md](pytest.md) | Unit, configuration, integration and end-to-end tests; coverage. |
| [ruff.md](ruff.md) | Linting and formatting. |
| [mypy.md](mypy.md) | Static type checking. |
| [import-linter.md](import-linter.md) | The layer and forbidden-import contracts. |
| [uv-and-lock-files.md](uv-and-lock-files.md) | The hash-pinned lock files and `pip-audit`. |
| [pyproject-toml.md](pyproject-toml.md) | Package metadata, commands and TOML. |
| [github-actions.md](github-actions.md) | The CI workflow. |
| [yaml.md](yaml.md) | The YAML features used by the configuration files. |
| [json.md](json.md) | JSON in the dashboard, the app, the APIs and the logs. |
| [git-and-editorconfig.md](git-and-editorconfig.md) | `.gitignore` and `.editorconfig`. |
