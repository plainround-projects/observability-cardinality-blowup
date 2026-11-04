# observability-cardinality-blowup

A checkout app and a real Prometheus that you overload on purpose with a `user_id` label: measure the series, memory and query time, find the offender from the backend's own statistics, move the detail to trace attributes, keep a guard against its return, and use traces to find a slow dependency that averaged metrics hide.

| | |
| --- | --- |
| **Lesson** | `/prep/observability/project-cardinality-blowup`, "Blow up metric cardinality, then fix it" (`data-structure-explainer/src/content/tracks/observability/13-project-cardinality-blowup.md` in the Plainround app) |
| **Planned hours** | 9 |
| **Level** | Intermediate |
| **Architecture** | [ARCHITECTURE.md](ARCHITECTURE.md), decisions in [docs/adr](docs/adr), the placement guide in [docs/label-placement-guide.md](docs/label-placement-guide.md) |

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/architecture-dark.svg">
  <img alt="The Docker Compose stack of the checkout app: Prometheus scrapes it on port 9100, the Collector sends spans to Tempo, Grafana reads both, and the Scenario drives it. The amber arrow is the scrape that carries the user_id label." src="docs/diagrams/architecture.svg">
</picture>

The amber edge is the scrape that carries the user_id label; the same detail travels as span attributes to Tempo, which has no series to multiply.

## How one run flows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/flow-dark.svg">
  <img alt="The Scenario runs six steps: baseline of 669 series, 494,226 with user_id, the offender read from Prometheus, a guarded fresh Prometheus, the label back behind the guard, and 41 slow traces found with TraceQL." src="docs/diagrams/flow.svg">
</picture>

Amber rows are the label that multiplies the series and the p95 that hides one slow tenant; the green box is where the run ends.

## Prerequisites

| Tool | Version | Used for |
| --- | --- | --- |
| Docker with Compose v2 | 24 or newer (tested with 24.0.6 and Compose v2.23); about 5 GB for the Docker VM at the lesson's full size, 2 GB at a tenth | the whole stack |
| Python | 3.12 or 3.13 (tested with 3.13; the CI and the image use 3.12) | the load generator, the scenario and the tests on your machine |
| GNU Make | 3.81 or newer (the one on macOS works) | every command below |
| Images | `prom/prometheus:v2.54.1`, `grafana/tempo:2.6.1`, `otel/opentelemetry-collector-contrib:0.111.0`, `grafana/grafana:11.2.0`; `python:3.12.8-slim-bookworm` is the base of the app image | pulled by Docker on first `make up` |
| Python packages | Flask, waitress, prometheus-client, requests and the OpenTelemetry distro, exporter and Flask instrumentation at run time; pytest, pytest-cov, ruff, mypy, import-linter, pip-audit for development. All pinned with hashes in `requirements.lock` and `requirements-dev.lock`; `make` installs them into `.venv/` | everything |

No cloud account, no secrets. The values in `.env.example` are local-only placeholders; `make up` copies them to `.env`. Every port is bound to `127.0.0.1`: the app on 28082, Grafana 23000, Prometheus 29090, Tempo 23200 (the app's `/metrics` on 9100 is not published; only Prometheus reaches it). Change any of them in `.env` if the port is taken.

## Setup, run, test, stop

```bash
make up                                  # builds the image, starts the app, Prometheus, the Collector, Tempo and Grafana, waits until healthy
make run                                 # the lesson's six steps at its full size: 50,000 users, 200,000 requests (30 minutes to an hour, mostly sending requests)
make run USERS=5000 REQUESTS=20000       # the same six steps at a tenth of the size
make load USERS=50000 REQUESTS=200000    # traffic only, to look at Grafana yourself
make health                              # the app, Prometheus, Tempo, and Grafana querying both
make check                               # format check, lint, types, import rules, unit tests with coverage, promtool config and rule tests
make test-integration                    # the running app, Prometheus and Tempo (needs make up first)
make test-e2e                            # the whole scenario at a tenth of the size, asserted number by number (needs make up first)
make audit                               # known-vulnerability check of the locked dependencies
make down                                # stops everything and deletes its data
```

`make help` lists every target. `make run` recreates the app and replaces Prometheus several times (see [ARCHITECTURE.md](ARCHITECTURE.md#one-run-step-by-step-make-run)), so do not run it while looking at a dashboard you want to keep. Grafana is at <http://localhost:23000> (user `admin`, password `GRAFANA_ADMIN_PASSWORD` from `.env`), dashboard "Cardinality blow-up".

`make run` prints one report at the end. This is `make run USERS=5000 REQUESTS=20000` (a tenth of the lesson's size) on a Mac with 12 cores and Docker's default 7.6 GB; the numbers repeat in order of magnitude, not exactly, and the full-size run is in the section after this one.

```text
1. Baseline: fresh Prometheus, three bounded labels
  sent 5000 requests from 3143 users at 1150/s
2. Blow it up: add the user_id label to both metrics and send the full traffic
  sent 20000 requests from 4902 users at 1192/s
3. Find the offender from Prometheus's own statistics
4. Fix: remove the label, keep user.id on the span, start from a fresh Prometheus with the guard
  sent 5000 requests from 3141 users at 813/s
5. Guard: someone adds user_id back; the scrape rule drops it before storage
  sent 5000 requests from 3170 users at 1032/s
6. Hidden slow dependency: one route, one tenant, found from traces
  sent 8000 requests from 3989 users at 1343/s
  sent 8000 requests from 4000 users at 886/s
Plan: 5000 users, 20000 requests

Expected series for the app (1 route x 1 method x 3 statuses): counter 3, histogram 24, total 27

                                series   memory MB  query ms  samples/scrape
baseline                           669          56         2              43
with user_id                     49973         133        12           49318
after the fix (fresh TSDB)         669          40         2              43
user_id re-added, guarded          671          77         1           29338
series growth with user_id: 75x (4902 distinct users in the traffic)

Offender from /api/v1/status/tsdb: label 'user_id' has 4902 values; metric 'request_latency_seconds_bucket' has 32886 series.
Traces for user-002343: 7 found, 7 requests sent.

Hidden slow dependency (tenant-0007, 0.51% of traffic): route p95 8.4 ms -> 47.8 ms.
Trace query on tenant + route + duration > 1 s: 41 traces of 41 slow requests, shortest 2000 ms.
```

Reading it: the series count grew 75 times for 4,902 distinct users (it grows with the number of users, not the number of requests); the stored series return to the baseline after the fix and stay there when the label comes back behind the guard. The `samples/scrape` column is what the app exposed after the guard's `labeldrop`: still about 29,000, because the colliding samples are counted before Prometheus discards them (that is the signal `MetricLabelGuardTriggered` and `AppSeriesBudgetExceeded` alert on), while the series in the head stay at 671. The memory and query-time columns move less than the series count at this size; at the lesson's size (50,000 users) they move by an order of magnitude.


## The lesson's own size: `make run`

The same six steps with 50,000 users and 200,000 requests (clean clone, 2026-11-02, about 50 minutes, on a host shared with other projects; load average 15 to 40). The series grow 739 times, Prometheus's memory about 25 times and the dashboard query about 40 times; the guard keeps the stored series at the baseline.

```text
1. Baseline: fresh Prometheus, three bounded labels
  sent 5000 requests from 4753 users at 1006/s
2. Blow it up: add the user_id label to both metrics and send the full traffic
  sent 200000 requests from 49094 users at 100/s
3. Find the offender from Prometheus's own statistics
4. Fix: remove the label, keep user.id on the span, start from a fresh Prometheus with the guard
  sent 50000 requests from 31533 users at 1167/s
5. Guard: someone adds user_id back; the scrape rule drops it before storage
  sent 50000 requests from 31606 users at 898/s
6. Hidden slow dependency: one route, one tenant, found from traces
  sent 8000 requests from 7389 users at 650/s
  sent 8000 requests from 7405 users at 567/s
Plan: 50000 users, 200000 requests

Expected series for the app (1 route x 1 method x 3 statuses): counter 3, histogram 24, total 27

                                series   memory MB  query ms  samples/scrape
baseline                           669          41         2              43
with user_id                    494226        1011        80          493567
after the fix (fresh TSDB)         669          48         2              43
user_id re-added, guarded          672         413         4          293101
series growth with user_id: 739x (49094 distinct users in the traffic)

Offender from /api/v1/status/tsdb: label 'user_id' has 49090 values; metric 'request_latency_seconds_bucket' has 329052 series.
Traces for user-045462: 6 found, 9 requests sent.

Hidden slow dependency (tenant-0007, 0.51% of traffic): route p95 36.0 ms -> 48.6 ms.
Trace query on tenant + route + duration > 1 s: 41 traces of 41 slow requests, shortest 2000 ms.
```

Two things to read in it. The line "Traces for user-045462: 6 found, 9 requests sent" came from the first version of the probe search, which gave up after 90 seconds while Tempo was still catching up on a loaded host; it now polls for up to 240 seconds like the slow-tenant search, and the tenth-size run above, with the final code, finds every request (7 of 7), as does `make test-e2e`. And the route p95 moves only from 36 ms to 49 ms while 41 requests take two seconds: the metric hides them, the trace query finds all 41.

## Verified

In fresh clones of the committed repository on 2026-11-02 (macOS, Docker 24.0.6, Python 3.13 for the lab tools; the host was shared with other projects, load average 10 to 40): `make up` (0), `make check` (ruff, mypy, import-linter, 90 unit and configuration tests, promtool config and rule tests: all passed), `make test-integration` (3 passed), `make test-e2e` (6 passed in 11 minutes 30 seconds), `make run` at the lesson's size (0, transcript above) and `make run USERS=5000 REQUESTS=20000` with the final code (0, first transcript), `make down` (0), clean tree afterwards. These runs found and fixed three things: the integration test read a label list that cannot be relied on to contain a one-value label (it now asks for the series directly), the p95 window was shorter than two scrapes on a fast host (it is now at least 180 seconds), and the trace searches gave up too early on a loaded host (240 seconds).

## Done when: the lesson's checklist and the proof for each line

| # | Done when (from the lesson) | Command | What proves it |
| --- | --- | --- | --- |
| 1 | You have the baseline series and memory numbers, and you can compute the expected series count from the labels' possible values. | `make run` (phase 1); `expected_series` | The first table row (head series, resident memory, dashboard query time, samples per scrape) and the line "Expected series for the app (1 route x 1 method x 3 statuses): counter 3, histogram 24, total 27", computed by `cardinality_lab.domain.series.expected_series` before anything is queried. The baseline also contains Prometheus's own series, which is why the head count is larger than 27. |
| 2 | The series count grows by orders of magnitude, and memory and a dashboard query's time grow with it, and you have all three numbers. | `make run` (phase 2) | The "with user_id" row and the "series growth" line. `tests/e2e` asserts growth of at least 10x on a tenth-size run, more memory, and at least 10x the samples per scrape; `tests/unit/infrastructure/test_prometheus_metrics.py` shows the multiplication in-process (200 users, 200 times the series). |
| 3 | The top entry is your `user_id` label, found from the statistics rather than from memory. | `make run` (phase 3); `curl -s localhost:29090/api/v1/status/tsdb \| jq '.data.labelValueCountByLabelName'` | The "Offender" line: the label with the most distinct values is `user_id`, with about as many values as there were distinct users in the traffic; the metric with the most series is the latency histogram's `_bucket`. The scenario reads only `/api/v1/status/tsdb`; it does not know which label was added. |
| 4 | The series count returns near the baseline, and you can still find all requests for one user through traces. | `make run` (phases 4 and 5) | The "after the fix (fresh TSDB)" and "user_id re-added, guarded" rows are within a factor of two of the baseline; the "Traces for user-..." line shows as many traces found by `user.id` as requests were sent for that user. The guard is `prometheus.guarded.yml` (a `labeldrop` on `user_id`), and the alert `MetricLabelGuardTriggered` fires when it has to act (promtool replay test). |
| 5 | You find the slow call by querying traces by attribute (route and tenant), and the README explains why the averaged metric hid it. | `make run` (phase 6) | The last two lines: the route's p95 before and after, and the TraceQL query `{ name = "checkout" && span.tenant.id = "tenant-0007" && span.route = "checkout" && duration > 1s }` returning the slow requests. The explanation is below. |
| 6 | The guide has a bounded-values rule for labels with an example of each kind. | read [docs/label-placement-guide.md](docs/label-placement-guide.md) | The rule (a label must have a bounded set of values you can list), a table with one example per kind drawn from this project (route/method/status as labels, `user.id` and `tenant.id` as span attributes, bodies and stack traces in logs only), and four steps to apply it. `tests/observability` checks the guide has the rule and the examples. |

**Why the averaged metric hid the slow tenant.** `tenant-0007` is 1 of 200 tenants (0.5% of the traffic). Its checkouts take two seconds longer, but they are 0.5% of the requests in the `checkout` histogram, so the route's median is untouched and the p95 (the point below which 95% of requests fall) is set by the other 99.5%, which are fast. Only a statistic at or above the 99.5th percentile would move, and the histogram's wide upper buckets (500 ms to 2.5 s) would blur even that. The metric is an aggregate across tenants by construction (the tenant is not a label, and cannot be: 200 values times every other label), so the slice has nothing of its own to show. A trace query scoped to the route and the tenant selects exactly that slice, so there is nothing fast to dilute it; each trace shows the two-second `payment.charge` span. That is also the placement rule at work: the tenant is a high-cardinality detail, so it lives on the span.


## Stretch goals

| Stretch (from the lesson) | Built? |
| --- | --- |
| Replace the latency histogram with native or exponential histograms and compare series counts. | No. [ARCHITECTURE.md](ARCHITECTURE.md#how-to-extend-it) says how: Prometheus's `native-histograms` feature flag and the client's native histogram. |
| Send wide events (one rich record per request) to a columnar store and answer the tenant question with one query. | No. |
| Add a cardinality limit in the Collector and see what happens when it is hit. | No. The guard is a scrape-time `labeldrop` in Prometheus, with the reasons and the Collector alternative in [ADR 0002](docs/adr/0002-guard-in-the-scrape-config-not-the-collector.md). |

## What is simplified for teaching

Only what the lesson scopes out, plus where this build differs from the lesson's text:

- One Prometheus with local disk, no remote write and no long-term store; a 3 GB memory cap on its container so the blown-up run cannot take Docker down.
- The "downstream call" is a simulated payment gateway with a configured delay, and the traffic comes from one load generator on the host.
- **The `user_id` label is a switch** (`METRICS_INCLUDE_USER_ID`, default `false`) that stands in for the lesson's code change, so one command can make the mistake, measure it and undo it ([ADR 0001](docs/adr/0001-the-mistake-is-a-switch-in-the-metrics-adapter.md)). It is dangerous by design and off unless the scenario turns it on.
- The metrics carry `route`, `method` and `status` as the lesson says, but the route and method come from the server (the matched route and the HTTP method), never from the client's query string; a client-chosen label value is itself a cardinality attack. `GET /checkout?route=X&method=GET` becomes `GET /checkout`.
- The latency histogram has five buckets, not the client library's eleven, so the blown-up run fits a laptop: about half a million series instead of more than a million ([ADR 0004](docs/adr/0004-five-latency-buckets.md)). The lesson's absolute numbers (198,340 series, 584 MB) differ; its orders of magnitude hold. The lesson's own figures are not consistent with each other either: its step 3 solution shows 1,150,000 bucket series in a run it reports as 198,340 series in total.
- The post-fix series count is measured on a fresh Prometheus, because an old one keeps series in its head for about two hours after their last sample ([ADR 0003](docs/adr/0003-a-fresh-prometheus-for-the-post-fix-measurement.md)).
- The guard is a `labeldrop` in the scrape config; the lesson allows "a relabeling or Collector rule", and the metrics never pass through a Collector here ([ADR 0002](docs/adr/0002-guard-in-the-scrape-config-not-the-collector.md)).
- The app is single-process on waitress; its OpenTelemetry providers are configured by `opentelemetry-instrument` and `OTEL_*` variables.

## Project structure

```text
src/cardinality_lab/
  domain/            UserId and TenantId (validated), CheckoutRequest, Outcome and OutcomePolicy, the slow-dependency
                     rule, and the series arithmetic (expected_series). Depends on nothing outside the standard library.
  application/       the Checkout use case and its ports (CheckoutMetrics, RequestTracer, PaymentGateway, Clock).
                     Depends on domain only.
  infrastructure/    adapters: the Prometheus metrics (with the user_id switch), the OpenTelemetry span, the simulated
                     payment gateway, settings (environment, validated), JSON logging, signal handling.
                     Depends on application and domain.
  interfaces/        the Flask app, the waitress runner, the composition root and the health command.
                     Depends on everything below; nothing depends on it.
  lab/               the experiment: load generator, Prometheus and Tempo clients, docker compose control, the six-phase
                     scenario and its report. A sibling of interfaces; the app never imports it.
tests/
  unit/              domain, application (with fakes), infrastructure, interfaces, lab. No containers.
  observability/     lints compose, the Collector, both Prometheus configs, the rules, the dashboard and the guide.
  integration/       the running app, Prometheus and Tempo.
  e2e/               the whole scenario at a tenth of the size, assertion by assertion.
observability/       the Collector, Tempo, Prometheus (baseline and guarded configs, alert rules, promtool replay test)
                     and Grafana (data sources, dashboard) as code.
docs/                label-placement-guide.md (lesson step 6) and the decision records in adr/.
tech/                one beginner-level note per technology the repository uses, with every file quoted and explained (start at tech/README.md).
docker-compose.yml   the stack.               Dockerfile  the app image (non-root, base image pinned by digest).
pyproject.toml       project metadata and every tool's configuration (ruff, mypy, pytest, import-linter).
requirements*.lock   hash-pinned dependencies (runtime, and runtime plus development tools).
Makefile             the only commands a reader needs (make help).
```

There is no `sql/` folder: nothing in this project touches a database.

The dependency rule (domain depends on nothing; application on domain; infrastructure on both; interfaces and lab on everything; nothing on them) is enforced by `make lint` through import-linter. A second contract forbids `domain` and `application` from importing Flask, prometheus_client, requests, OpenTelemetry or waitress.

## Troubleshooting

- **A port is in use:** change the matching `*_HOST_PORT` in `.env` and run `make up` again.
- **`make run` is slow or times out on a busy machine:** the full size sends over 300,000 requests; run it with `USERS=5000 REQUESTS=20000`. The health checks wait up to ten minutes per container.
- **Prometheus is killed (exit 137) in the blown-up phase:** Docker's VM has less than 3 GB free for it; raise the VM memory in Docker Desktop or use the smaller size.
- **Start clean:** `make down && make up` (the volumes are deleted).

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE). Changes are in [CHANGELOG.md](CHANGELOG.md).
