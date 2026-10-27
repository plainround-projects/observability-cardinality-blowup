# 3. A fresh Prometheus for the post-fix measurement

Status: accepted, 2026-10-27

## Context

The lesson says the series count returns to about 1,849 after the fix. Prometheus keeps a series in its head block until
the head is truncated at the next compaction, about two hours after the last sample. In the same instance
`prometheus_tsdb_head_series` therefore stays at the blown-up value for hours after the label is gone, however quickly
the fix is deployed.

## Decision

Step 4 replaces Prometheus with a new instance (and an empty volume) before measuring. The report labels that row "after
the fix (fresh TSDB)". The samples-per-scrape number, which does fall immediately, is reported next to it.

## Alternatives considered

- **Wait two hours.** Not a scenario anyone reruns.
- **Delete the series through the admin API and clean tombstones.** Marks data deleted but does not shrink the head
  promptly, and needs `--web.enable-admin-api`, which has no business in a lab others will copy.
- **Measure `count({job="checkout"})`.** Falls immediately, but it is a different number from the one the lesson uses.

## Consequences

- The README states the two-hour fact, which is itself an interview answer: fixing a cardinality problem is not instant
  relief, and a restart or the head's truncation is what releases the memory.
