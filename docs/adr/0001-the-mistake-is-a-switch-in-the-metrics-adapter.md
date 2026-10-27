# 1. The user_id label is a switch in the metrics adapter

Status: accepted, 2026-10-27

## Context

The lesson's step 2 is a code change: add `user_id` to both metrics and rerun the traffic. The scenario must make that
change, measure it, and undo it (step 4), in one repeatable run, and `make run` must work from a fresh clone.

## Decision

`PrometheusCheckoutMetrics` takes `include_user_id`. With it false the labels are `route`, `method`, `status`; with it
true they also include `user_id`. The flag comes from `METRICS_INCLUDE_USER_ID` (default false) and the scenario sets it
when it recreates the app.

## Alternatives considered

- **Two app builds, a safe one and an unsafe one.** Doubles the images and hides that the only difference is one label.
- **Patch the source during the run.** Not repeatable, and a scenario that edits code is a scenario nobody trusts.
- **Make the unsafe version the only version.** Then there is nothing to fix.

## Consequences

- The mistake is one adapter and one flag, easy to point at in review.
- The switch is dangerous in production, so its default is off, it is named for what it does, and the README says it
  stands in for the code change.
- The `user_id` is passed to the adapter in every mode (the port's signature carries it); only the adapter decides
  whether it becomes a label. The tracing adapter always puts it on the span.
