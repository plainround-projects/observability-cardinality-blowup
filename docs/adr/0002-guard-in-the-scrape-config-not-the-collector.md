# 2. The guard is a `labeldrop` in Prometheus's scrape config, not a Collector processor

Status: accepted, 2026-10-27

## Context

The lesson asks for "a relabeling or Collector rule that drops it if someone adds it back", and its solution shows both:
an `attributes` processor in the Collector, or `metric_relabel_configs` "if staying Prometheus-only".

## Decision

The app exposes its metrics with the Prometheus client library and Prometheus scrapes them directly; no metric passes
through the Collector, which carries traces only. So the guard is `metric_relabel_configs: [{action: labeldrop, regex:
user_id}]` on the `checkout` job, in `prometheus.guarded.yml`. A test checks that this file differs from the baseline
config by that block and nothing else.

## Alternatives considered

- **A Collector `attributes` processor on a metrics pipeline.** Requires sending the metrics over OTLP (changing the
  instrumentation the lesson starts with), and deleting an attribute from OTLP points does not merge the points, so the
  exporter still sees colliding series.
- **`action: drop` on series with a `user_id`.** Protects the store but silently removes the whole metric.
- **`sample_limit` on the job.** Fails the whole scrape when exceeded, so a mistake turns a cardinality problem into a
  missing-data problem.

## Consequences

- After a re-add, series stay at the baseline, but the dropped label's series collide: Prometheus keeps the first sample
  per scrape and counts the rest in `prometheus_target_scrapes_sample_duplicate_timestamp_total`. The counter's value is
  wrong (the cardinality is protected, the data is not), which is why `MetricLabelGuardTriggered` alerts on that counter.
- The guard lives with the store that pays for the mistake, and nothing in the app needs to know about it.
