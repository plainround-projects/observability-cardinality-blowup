# 4. Five latency buckets, not eleven

Status: accepted, 2026-10-27

## Context

With a `user_id` label, every distinct user creates one counter series and one histogram series per bucket plus `_sum`,
`_count` and `+Inf`. The client library's default histogram has eleven finite buckets. At 50,000 users that is over a
million series and several gigabytes in Prometheus, more than the Docker VM on a laptop can give, and other work shares
it. The lesson's own numbers (198,340 series, 584 MB) correspond to about four series per user.

## Decision

The latency histogram has five finite buckets: 5 ms, 10 ms, 50 ms, 500 ms and 2.5 s. That is eight series per label
combination and about half a million series for the blown-up run. Prometheus runs with a 3 GB memory limit so a runaway
cannot take the Docker VM down.

## Alternatives considered

- **Default buckets.** Over a million series; fails on a laptop.
- **Fewer users.** The lesson fixes 50,000; the make variables `USERS` and `REQUESTS` still allow a smaller run.

## Consequences

- Absolute numbers differ from the lesson's (the lesson says the orders of magnitude should match, and they do).
- The p95 is interpolated within wide buckets, so the "barely moved" comparison in step 6 is coarse; the trace query, not
  the percentile, is the evidence the lesson asks for.
