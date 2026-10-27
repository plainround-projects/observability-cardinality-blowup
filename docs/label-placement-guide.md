# Where does this detail go: metric label, span attribute, or log?

One rule decides: **a metric label must have a bounded set of values, small enough to list in a review.** Every
distinct combination of label values is its own time series in the metrics store, and series count (not request
volume) drives memory, storage cost and query time. A span attribute is stored once per trace, so it can hold a value
that is different on every request. A log line holds anything that is too large or too free-form for either.

| Detail | Goes in | Why | Example from this project |
|---|---|---|---|
| Route, method, status | **metric label** | bounded: one route, one method, three statuses | `requests_total{route="checkout",method="GET",status="200"}`: 3 series |
| User id, order id, request id | **span attribute** | unbounded: one value per user or request | `user.id="user-012345"` on the `checkout` span; all of one user's requests are one trace search away |
| Tenant id | **span attribute** (and a label only if the tenant list is short and fixed) | hundreds of values multiply every series by hundreds | `tenant.id="tenant-0007"` found the slow downstream call that the route's p95 hid |
| Full request or response body, a stack trace, a free-text error message | **logs only** | large and free-form: even a span attribute pays for it on every trace | the JSON log line of a declined checkout carries the outcome and tenant; a stack trace would live there too |

## How to apply it

1. Before adding a label, write down its possible values. If you cannot list them, or the list grows with users,
   orders or time, it is not a label.
2. Compute the cost on paper: series = (product of the label cardinalities) for a counter, and that times
   (buckets + 3) for a histogram. `cardinality_lab.domain.series.expected_series` does the arithmetic.
3. Put the detail on the span (`span.set_attribute("user.id", ...)`) and query it with the trace store
   (`{ span.user.id = "user-012345" }`).
4. Keep a guard in the metrics pipeline (`prometheus.guarded.yml` drops `user_id`) and an alert on the series count, so
   the same mistake six months from now is caught by a machine.
