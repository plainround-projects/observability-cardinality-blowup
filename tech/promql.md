# PromQL

## What it is

PromQL is the query language of Prometheus. A query is an **expression** that produces numbers from stored series. You type it in the Prometheus UI, in a Grafana panel, or in an alert rule. There is no `SELECT`: you name a metric, narrow it with label matchers in braces, and apply functions.

## Why this repository uses it

Every number in the lesson is a PromQL query: how many series Prometheus holds, how much memory it uses, how many samples a scrape returned, how long the dashboard query takes, and the p95 that hides a slow tenant. The alert expressions and the dashboard panels are PromQL too.

## Where it appears

| Path | Expression |
| --- | --- |
| `src/cardinality_lab/lab/prometheus.py` | The lesson's three measurements and the timed dashboard query. |
| `src/cardinality_lab/lab/scenario.py` | The p95 of the whole route. |
| `observability/prometheus/rules/cardinality.rules.yml` | The three alert expressions. |
| `observability/grafana/dashboards/cardinality-blowup.json` | One expression per metric panel. |

## How it works underneath

- A **selector** `metric{label="value"}` picks series. `=` is equal, `!=` is not equal, `=~` matches a regular expression.
- A **range vector** `metric[1m]` is the last minute of points of each selected series.
- `rate(counter[1m])` is the per-second increase of a counter, averaged over the range; it handles counter resets.
- `sum(...)` adds series together. `sum by (label) (...)` keeps the named label and adds the rest. `sum without (label)` drops the named label.
- `histogram_quantile(0.95, sum by (le) (rate(x_bucket[1m])))` estimates the 95th percentile from histogram buckets: it finds the bucket where 95% of observations have been counted and interpolates inside it. The result is an estimate that depends on the bucket boundaries.
- Arithmetic between two results matches series by identical label sets; `sum(...)` without `by` leaves one series with no labels, which makes `sum(a) / sum(b)` match.
- A comparison such as `> 0.02` filters: the expression returns a value only where the comparison is true; for an alert, "returns something" means "fire".
- An **instant query** evaluates at one time. A **range query** evaluates at many times (`start`, `end`, `step`) and is what a graph uses.

## Walkthrough of this repository's use

### The metric names in this repository

The app exposes `requests_total{route, method, status}` and the histogram `request_latency_seconds` (`_bucket{le}`, `_sum`, `_count`), plus `user_id` when the mistake is on. Prometheus adds `up`, `scrape_duration_seconds`, `scrape_samples_scraped` and `scrape_samples_post_metric_relabeling` for every target, and exposes its own `prometheus_tsdb_head_series`, `process_resident_memory_bytes` and `prometheus_target_scrapes_sample_duplicate_timestamp_total`.

### The lesson's three numbers

```python
SERIES_COUNT_QUERY = "prometheus_tsdb_head_series"
MEMORY_QUERY = 'process_resident_memory_bytes{job="prometheus"}'
DASHBOARD_QUERY = "sum(rate(requests_total[5m])) by (route)"
```

`prometheus_tsdb_head_series` is a gauge: the number of series in the head right now. `process_resident_memory_bytes{job="prometheus"}` is the memory (resident set size) of the Prometheus process, selected by the label `job`. The third is the dashboard query: `rate(requests_total[5m])` is requests per second averaged over five minutes for *each series*; `sum(...) by (route)` adds them per route. The cost of this query grows with the number of series it must read, which is what the lesson measures: with a `user_id` label, it must read tens of thousands of series to return one row.

```python
    def samples_per_scrape(self, job: str) -> int:
        """Samples the last scrape of ``job`` returned after relabeling."""
        return int(self.scalar(f'scrape_samples_post_metric_relabeling{{job="{job}"}}'))
```

`scrape_samples_post_metric_relabeling{job="checkout"}` is how many samples the last scrape of the app yielded after the relabeling rules ran: about 75 at the baseline, hundreds of thousands with the mistake.

```python
    def wait_for_scrapes(self, job: str, scrapes: int = 2, timeout_seconds: float = 900.0) -> None:
        """Block until the target ``job`` has been scraped ``scrapes`` more times since this call."""
        start = self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])')
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self.scalar(f'count_over_time(scrape_duration_seconds{{job="{job}"}}[1h])') >= start + scrapes:
                return
            time.sleep(2.0)
        raise PrometheusError(f"{job} was not scraped {scrapes} times within {timeout_seconds:.0f}s")
```

`count_over_time(scrape_duration_seconds{job="checkout"}[1h])` counts how many scrapes happened in the last hour: each scrape writes one `scrape_duration_seconds` sample. The client reads it before and after and waits until it has grown, which proves that new scrapes arrived.

### The route p95 that hides a slow tenant

```python
    def _route_p95(self, window_seconds: float) -> float:
        expression = (
            "histogram_quantile(0.95, sum by (le) "
            f'(increase(request_latency_seconds_bucket{{job="{JOB}"}}[{int(window_seconds)}s])))'
        )
        return self._prometheus.scalar(expression)
```

`increase(request_latency_seconds_bucket{job="checkout"}[Ns])` is how many observations each bucket gained in the last N seconds (N is the length of the traffic phase plus 45 s). `sum by (le)` adds the series of every status, keeping the bucket edge. `histogram_quantile(0.95, ...)` estimates the 95th percentile. Because one tenant out of 200 is under one percent of traffic, making that tenant's requests two seconds slow barely moves a p95: the lesson's point that averages and percentiles hide a small slice.

### The alert expressions

```yaml
        expr: scrape_samples_post_metric_relabeling{job="checkout"} > 1000
```

`scrape_samples_post_metric_relabeling{job="checkout"} > 1000`: the filter `> 1000` keeps the series only while the value exceeds 1000.

```yaml
        expr: prometheus_tsdb_head_series > 100000
```

`prometheus_tsdb_head_series > 100000`.

```yaml
        expr: increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m]) > 0
```

`increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m]) > 0`: `increase` of a counter over five minutes; above zero means collisions happened.

### The dashboard

The dashboard (`grafana.md`) uses, for its panels: `prometheus_tsdb_head_series`, `process_resident_memory_bytes{job="prometheus"}`, `scrape_samples_post_metric_relabeling{job="checkout"}`, `increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m])`, `scrape_samples_scraped{job="checkout"}` (before relabeling), `sum by (status) (rate(requests_total[1m]))`, the p95 `histogram_quantile(0.95, sum by (le) (rate(request_latency_seconds_bucket[1m])))`, and `prometheus_engine_query_duration_seconds{slice="inner_eval",quantile="0.9"}` (how long Prometheus's own query engine spends evaluating, the 90th percentile).

## Try it yourself

```bash
curl -s --get "http://127.0.0.1:29090/api/v1/query" --data-urlencode 'query=prometheus_tsdb_head_series'
```

Expected (needs `make up`): a result with a value near 1,800 at the baseline.

```bash
curl -s --get "http://127.0.0.1:29090/api/v1/query" --data-urlencode 'query=scrape_samples_post_metric_relabeling{job="checkout"}'
```

Expected: a value near 75.

```bash
curl -s --get "http://127.0.0.1:29090/api/v1/query" --data-urlencode 'query=sum(rate(requests_total[5m])) by (route)' --data-urlencode 'stats=all' | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['result'], d['stats']['timings']['evalTotalTime'])"
```

Expected (after `make load USERS=500 REQUESTS=2000`): one row for the route `checkout` and the engine's evaluation time in seconds.

```bash
curl -s --get "http://127.0.0.1:29090/api/v1/query" --data-urlencode 'query=count by (__name__) ({__name__=~".+"}) > 100' | python3 -m json.tool | head -20
```

Expected: the metric names with more than 100 series; at the baseline, only histogram buckets of Prometheus itself.

```bash
.venv/bin/python -m pytest tests/unit/lab/test_prometheus_client.py -q
```

Expected: `6 passed`.

## Mistakes people make

- **`rate()` on a histogram `_bucket` without summing by `le`** first.
- **Averaging percentiles** across instances. Sum the buckets, then take the quantile.
- **Dividing by zero** when traffic stops: the result is `NaN`, and a comparison with NaN is false.
- **Forgetting that quoting rules** differ in JSON (`\"`) and YAML.

## Check yourself

1. What does `rate(x[1m])` return? *The per-second increase of a counter averaged over the last minute.*
2. What does `sum by (le) (...)` keep? *Only the `le` label; other labels are added together.*
3. How do you estimate the p95 from a histogram? *`histogram_quantile(0.95, sum by (le) (rate(..._bucket[...])))`.*
4. What does `metric[5m]` mean? *A range vector: all points of the last five minutes.*
5. What does `>` do in an alert expression? *Filters results to those greater than the number; a non-empty result fires the alert.*

## Further reading

- Querying basics: https://prometheus.io/docs/prometheus/2.54/querying/basics/
- Functions: https://prometheus.io/docs/prometheus/2.54/querying/functions/
- Operators: https://prometheus.io/docs/prometheus/2.54/querying/operators/
- Histograms and summaries: https://prometheus.io/docs/practices/histograms/
