# Changelog

All notable changes to this project are recorded here. The format follows Keep a Changelog and the project uses
semantic versioning.

## [Unreleased]

### Added

- Drawn architecture and flow figures in `docs/diagrams/`, light and dark, shown in the README.

## [0.1.0] - 2026-10-27

### Added

- A checkout app with a request counter and a latency histogram labeled by route, method and status, and a switch that
  adds a `user_id` label (the lesson's mistake), behind a real Prometheus.
- A load generator for 50,000 users and 200 tenants, and a scenario that measures the baseline, blows the series count
  up, finds the offender from `/api/v1/status/tsdb`, fixes it, guards against its return and finds a slow tenant from
  traces.
- `user.id`, `tenant.id` and `route` as span attributes, a Collector and Tempo, and a TraceQL search that returns one
  user's requests.
- A `labeldrop` guard in the scrape config, alert rules on series count and scrape size with promtool replay tests, and a
  dashboard as code.
- The label placement guide, unit, integration and end-to-end tests, ruff, mypy and import-linter checks, and a CI
  workflow.
