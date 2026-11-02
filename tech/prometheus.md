# Prometheus (v2.54.1), its rules and promtool

## What it is

Prometheus is a database for metrics and a program that **scrapes** them. A **scrape** is an HTTP GET that Prometheus makes every few seconds to a **target** (an address that publishes its current numbers as plain text). Prometheus stores each number with its time stamp in a **time series database** (TSDB). A **time series** is one metric name plus one exact set of **labels** (key/value pairs such as `service_name="back"`), with a list of (time, value) points.

You ask Prometheus questions in **PromQL**, its query language. Prometheus can also evaluate **rules** on a schedule: **recording rules** save a result as a new metric; **alerting rules** fire an alert when an expression returns something for long enough. This repository pins Prometheus v2.54.1.

## Why this repository uses it

Prometheus is both the victim and the instrument of this lesson. The mistake (a `user_id` label) overloads it. Its own statistics endpoint (`/api/v1/status/tsdb`) names the offender. Its scrape configuration is where the guard lives (`metric_relabel_configs` with `labeldrop`), so a careless code change cannot recreate the problem. Its alert rules watch for the symptoms, and `promtool` tests those rules offline.

## Where it appears

| Path | What it does |
| --- | --- |
| `observability/prometheus/prometheus.yml` | The baseline configuration: scrape the app every 60 s, and Prometheus itself. |
| `observability/prometheus/prometheus.guarded.yml` | The same plus the guard that drops `user_id`. |
| `observability/prometheus/rules/cardinality.rules.yml` | Three alert rules. |
| `observability/prometheus/tests/cardinality.rules.test.yml` | The promtool unit tests of those rules. |
| `docker-compose.yml` (service `prometheus`) | The pinned image, flags, mounts, a 3 GB memory cap and a health check. |
| `src/cardinality_lab/lab/compose.py`, `lab/prometheus.py` | Swap the configuration, reset the database, query the statistics (see `python-subprocess.md`, `requests.md`). |
| `Makefile` (`lint-config`, `test-rules`) | Run `promtool` in throw-away containers. |

## How it works underneath

Prometheus is **pull-based**: the targets do not send; Prometheus asks. In this repository the application sends OTLP to the Collector, the Collector converts it to the Prometheus text format on port 8889, and Prometheus scrapes that port every `scrape_interval`.

Metric types:

- A **counter** only goes up (reset to zero when a process restarts). Its name usually ends in `_total`.
- A **gauge** goes up and down.
- A **histogram** is stored as several series: `<name>_bucket{le="X"}` counts observations less than or equal to X (cumulative), `<name>_sum` is the sum of all observations, and `<name>_count` is how many there were. `le` means "less than or equal". The bucket `le="+Inf"` equals the count.

**Exemplars** are stored in a separate in-memory area enabled by `--enable-feature=exemplar-storage`, and are only readable if the scrape used the OpenMetrics format.

An **alert** goes through states: *inactive* (the expression returns nothing), *pending* (it returns something, but not for the `for:` duration yet), *firing*. A `for: 1m` means the expression must stay true across evaluations for a full minute. Prometheus sends firing alerts to Alertmanager (not used in this repository); here you see them in the UI.

`promtool` is the command-line companion. `promtool check config` validates the main file and the rule files it lists. `promtool test rules` runs a **unit test** for rules: you give fake input series and the time points to check, and it tells you whether the alert fires. The test never contacts a real Prometheus.

Storage lives in a folder (`--storage.tsdb.path`). Data older than `--storage.tsdb.retention.time` is deleted.

**What a label does to storage.** Prometheus keeps one time series for each distinct set of labels. To find a series quickly it keeps an in-memory **index** in the **head block**, the newest couple of hours of data. Every series costs memory in the head (the label strings, the index entries, a chunk being written), and every query that touches the metric has to consider all of its series. So memory, scrape size and query time all grow with the **number of series**, not with the number of requests. A label with N values on a metric with M other combinations makes N × M series. This is **cardinality**.

**Where Prometheus tells you the offender.** `GET /api/v1/status/tsdb` returns head statistics: `seriesCountByMetricName` (series per metric), `labelValueCountByLabelName` (distinct values per label name) and others. By default each list holds the top 10; `?limit=50` returns 50. The label with thousands of values is the culprit.

**Why a fresh Prometheus.** A series stays in the head for roughly two hours after its last sample before the next compaction removes it, so after fixing the app the old series still count. The lab starts a new Prometheus with an empty data folder to measure the steady state at once.

**Relabeling.** Before Prometheus stores a scraped sample it can run **relabeling** rules. `metric_relabel_configs` runs on each scraped sample *after* the scrape and *before* storage. The action `labeldrop` with `regex: user_id` deletes every label whose name matches the regex. After the drop, the samples of different users have identical label sets, so they collide: Prometheus keeps one sample per scrape and counts the rest in the counter `prometheus_target_scrapes_sample_duplicate_timestamp_total`. The stored series stay at the baseline.

## Walkthrough of this repository's use

### `prometheus.yml`: the baseline

```yaml
# Baseline configuration: scrapes the app exactly as it exposes itself. prometheus.guarded.yml adds the guard.
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/rules/*.rules.yml
```

The comment names the role of the file. `scrape_interval: 15s` and `evaluation_interval: 15s` are the defaults. `rule_files` loads every file matching `/etc/prometheus/rules/*.rules.yml`.

```yaml
scrape_configs:
  - job_name: checkout
    # A blown-up app serves tens of megabytes per scrape; give it time and a longer interval.
    scrape_interval: 60s
    scrape_timeout: 55s
    static_configs:
      - targets: ["app:9100"]
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

Job `checkout` overrides the interval: `scrape_interval: 60s` and `scrape_timeout: 55s`. The comment says why: a blown-up app serves tens of megabytes per scrape; it needs time to produce the page and Prometheus needs time to read it (the timeout must not exceed the interval). The target is `app:9100`, the app's metrics port on the Compose network. Job `prometheus` scrapes the server itself at `localhost:9090`, which gives the lesson its memory and series numbers (`process_resident_memory_bytes{job="prometheus"}`, `prometheus_tsdb_head_series`).

### `prometheus.guarded.yml`: baseline plus the guard

```yaml
# Baseline configuration plus the guard: any user_id label is stripped from the app's series before they are stored,
# so a careless code change cannot recreate the cardinality explosion. The test in tests/observability checks that
# this file differs from prometheus.yml only by the metric_relabel_configs block.
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/rules/*.rules.yml

scrape_configs:
  - job_name: checkout
    # A blown-up app serves tens of megabytes per scrape; give it time and a longer interval.
    scrape_interval: 60s
    scrape_timeout: 55s
    static_configs:
      - targets: ["app:9100"]
```

The header says a test checks that this file differs from the baseline only by the relabeling block. The first part is identical to the baseline.

```yaml
    metric_relabel_configs:
      # Removing the label makes the series of different users identical, so Prometheus keeps one sample per scrape
      # and counts the rest in prometheus_target_scrapes_sample_duplicate_timestamp_total, which the
      # MetricLabelGuardTriggered alert watches.
      - action: labeldrop
        regex: user_id
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

`metric_relabel_configs` is a list of rules applied to the samples of this job. The rule `action: labeldrop` with `regex: user_id` removes the label named `user_id` from every sample, whatever the metric. The comment explains the consequence: the colliding samples are counted in `prometheus_target_scrapes_sample_duplicate_timestamp_total`, which the third alert watches. The `prometheus` job follows unchanged.

### The Compose service

```yaml
  prometheus:
    image: prom/prometheus:v2.54.1
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=1d
    volumes:
      # The scenario swaps this file for prometheus.guarded.yml, the one with the metric_relabel_configs guard.
      - ${PROMETHEUS_CONFIG:-./observability/prometheus/prometheus.yml}:/etc/prometheus/prometheus.yml:ro
      - ./observability/prometheus/rules:/etc/prometheus/rules:ro
      - prometheus-data:/prometheus
    ports:
      - "127.0.0.1:${PROMETHEUS_HOST_PORT:-29090}:9090"
    # Half a million series need about two gigabytes; the cap keeps a runaway from taking the Docker VM down.
    mem_limit: 3g
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O - http://localhost:9090/-/healthy"]
      interval: 10s
      timeout: 10s
      retries: 60
      start_period: 30s
```

The flags: `--config.file`, `--storage.tsdb.path=/prometheus` (a named volume, so the data lives outside the container) and `--storage.tsdb.retention.time=1d`. The first mount is the key line: `${PROMETHEUS_CONFIG:-./observability/prometheus/prometheus.yml}` is the configuration file, chosen by an environment variable; the scenario sets it to the guarded file for phases 4 to 6. `mem_limit: 3g` caps the container's memory at 3 gigabytes: the comment says half a million series need about 2 GB, and the cap keeps a runaway from taking the whole Docker VM down. The health check calls `/-/healthy` with `wget`.

### `cardinality.rules.yml`: three alerts

```yaml
groups:
  - name: cardinality
    rules:
      # The app's own scrape: a handful of series is normal, thousands means a label has gone unbounded.
      - alert: AppSeriesBudgetExceeded
        expr: scrape_samples_post_metric_relabeling{job="checkout"} > 1000
        for: 1m
        labels:
          severity: page
        annotations:
          summary: The checkout app exposes more than 1,000 samples per scrape.
          description: "{{ $value }} samples per scrape; the expected count is under 200."
          runbook: Open /api/v1/status/tsdb and read labelValueCountByLabelName; the label with thousands of values is the culprit.
```

Alert 1, `AppSeriesBudgetExceeded`: `scrape_samples_post_metric_relabeling{job="checkout"} > 1000`. This built-in series records how many samples the last scrape of the app produced after relabeling. A handful is normal (the baseline is about 75); thousands means a label went unbounded. `for: 1m` requires it to hold for a minute. Severity `page`. The `runbook` annotation says where to look: `/api/v1/status/tsdb`, the label with thousands of values.

```yaml
      # Prometheus itself: total active series in the head block.
      - alert: PrometheusHeadSeriesHigh
        expr: prometheus_tsdb_head_series > 100000
        for: 2m
        labels:
          severity: page
        annotations:
          summary: Prometheus holds more than 100,000 active series.
          description: "{{ $value }} active series; memory and query time grow with this number."
          runbook: Check seriesCountByMetricName at /api/v1/status/tsdb and fix the metric that owns most of them.
```

Alert 2, `PrometheusHeadSeriesHigh`: `prometheus_tsdb_head_series > 100000` for two minutes, severity `page`. It watches Prometheus itself.

```yaml
      # The guard in prometheus.guarded.yml strips user_id, so a re-added label shows up as duplicate samples.
      - alert: MetricLabelGuardTriggered
        expr: increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m]) > 0
        for: 1m
        labels:
          severity: ticket
        annotations:
          summary: The scrape guard is dropping a label and series are colliding.
          description: "{{ $value }} duplicate samples in 5 minutes; a metric gained a label the guard removes."
          runbook: Find the metric with the new label in the app's code and move the detail to a span attribute.
```

Alert 3, `MetricLabelGuardTriggered`: `increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m]) > 0` for a minute, severity `ticket`. If the guard is dropping a label, series collide and this counter grows, telling the team that someone added a label the guard removes: a ticket, not a page, because the guard has already protected the database.

### `cardinality.rules.test.yml`: the offline tests

```yaml
# Replays the lesson's two states through the rule file with promtool: the baseline (a few dozen samples per scrape,
# about 1,800 head series) and the blow-up (hundreds of thousands). Run with: make test-rules
rule_files:
  - ../rules/cardinality.rules.yml

evaluation_interval: 15s

tests:
```

The tests replay fake data through the rule file with `promtool`. `rule_files` is relative to the test file.

```yaml
  - name: baseline numbers stay silent
    interval: 15s
    input_series:
      - series: 'scrape_samples_post_metric_relabeling{job="checkout"}'
        values: "75x40"
      - series: "prometheus_tsdb_head_series"
        values: "1842x40"
      - series: 'prometheus_target_scrapes_sample_duplicate_timestamp_total{}'
        values: "0x40"
    alert_rule_test:
      - eval_time: 9m
        alertname: AppSeriesBudgetExceeded
        exp_alerts: []
      - eval_time: 9m
        alertname: PrometheusHeadSeriesHigh
        exp_alerts: []
      - eval_time: 9m
        alertname: MetricLabelGuardTriggered
        exp_alerts: []
```

Test 1, baseline numbers stay silent. The notation `"75x40"` means the value 75 repeated 40 times (here one sample per 15 s). The three fake series are the baseline: 75 samples per scrape, 1,842 head series, no duplicates. At 9 minutes none of the three alerts may be firing (`exp_alerts: []`).

```yaml
  - name: a user_id label makes the budget and head-series alerts fire after their for-durations
    interval: 15s
    input_series:
      # The label arrives at minute 2: samples per scrape jump from 75 to 331,000, head series to 198,340.
      - series: 'scrape_samples_post_metric_relabeling{job="checkout"}'
        values: "75x8 331000x32"
      - series: "prometheus_tsdb_head_series"
        values: "1842x8 198340x32"
    alert_rule_test:
      - eval_time: 2m30s
        alertname: AppSeriesBudgetExceeded
        exp_alerts: []
      - eval_time: 4m
        alertname: AppSeriesBudgetExceeded
        exp_alerts:
          - exp_labels:
              severity: page
              job: checkout
            exp_annotations:
              summary: The checkout app exposes more than 1,000 samples per scrape.
              description: "331000 samples per scrape; the expected count is under 200."
              runbook: Open /api/v1/status/tsdb and read labelValueCountByLabelName; the label with thousands of values is the culprit.
      - eval_time: 5m
        alertname: PrometheusHeadSeriesHigh
        exp_alerts:
          - exp_labels:
              severity: page
            exp_annotations:
              summary: Prometheus holds more than 100,000 active series.
              description: "198340 active series; memory and query time grow with this number."
              runbook: Check seriesCountByMetricName at /api/v1/status/tsdb and fix the metric that owns most of them.
```

Test 2, a `user_id` label arrives. `"75x8 331000x32"` means 75 eight times, then 331,000 thirty-two times: the label arrives at minute 2. At 2m30s the budget alert is still *pending* (it has not held for a full minute), so no alert; at 4 minutes `AppSeriesBudgetExceeded` fires with the exact labels (`severity: page`, `job: checkout`) and annotations (the description shows `331000`); at 5 minutes `PrometheusHeadSeriesHigh` fires with `198340`.

```yaml
  - name: the scrape guard colliding series raises a ticket
    interval: 15s
    input_series:
      # The counter starts increasing at minute 1 (the guard strips user_id and samples collide).
      - series: "prometheus_target_scrapes_sample_duplicate_timestamp_total"
        values: "0x4 0+400x36"
    alert_rule_test:
      - eval_time: 30s
        alertname: MetricLabelGuardTriggered
        exp_alerts: []
      - eval_time: 4m
        alertname: MetricLabelGuardTriggered
        exp_alerts:
          - exp_labels:
              severity: ticket
            exp_annotations:
              summary: The scrape guard is dropping a label and series are colliding.
              description: "4400 duplicate samples in 5 minutes; a metric gained a label the guard removes."
              runbook: Find the metric with the new label in the app's code and move the detail to a span attribute.
```

Test 3, the guard raises a ticket. `"0x4 0+400x36"` means 0 four times, then start at 0 and add 400 each step for 36 steps: the counter starts climbing at minute 1. At 30 seconds nothing fires; at 4 minutes `MetricLabelGuardTriggered` fires with `4400` duplicate samples in five minutes.

### How `make` runs them

```makefile
lint-config: ## promtool checks both Prometheus configs and the rules; the Collector validates its config
	docker run --rm --entrypoint promtool -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) \
	  check rules /etc/prometheus/rules/cardinality.rules.yml
	docker run --rm --entrypoint sh -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) -c \
	  'mkdir -p /tmp/rules && cp /etc/prometheus/rules/*.yml /tmp/rules/ && for f in prometheus.yml prometheus.guarded.yml; do sed "s#/etc/prometheus/rules#/tmp/rules#" /etc/prometheus/$$f > /tmp/$$f && promtool check config /tmp/$$f || exit 1; done'
	docker run --rm -v "$(CURDIR)/observability/collector/config.yaml:/etc/otelcol/config.yaml:ro" $(COLLECTOR_IMAGE) \
	  validate --config=/etc/otelcol/config.yaml
```

`lint-config` has three commands. The first runs `promtool check rules` on the rule file. The second is the clever one: `promtool check config` validates a configuration *including the rule files it names*, but the configurations name `/etc/prometheus/rules/...`, a path that exists only inside the real container. So the recipe starts a throw-away container with `sh -c`, copies the rules to `/tmp/rules`, uses `sed` to rewrite the path in a temporary copy of each configuration (`s#/etc/prometheus/rules#/tmp/rules#`; `#` is the separator so the slashes need no escaping), and runs `promtool check config` on both the baseline and the guarded file, stopping with `exit 1` at the first failure. `$$f` has two dollar signs because Make turns `$$` into `$` before the shell sees it. The third command validates the Collector's file.

```makefile
test-rules: ## replay series through promtool and assert the alerts fire (and stay silent when they should)
	docker run --rm --entrypoint promtool -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) \
	  test rules /etc/prometheus/tests/cardinality.rules.test.yml
```

`test-rules` runs `promtool test rules` on the test file.

## Try it yourself

```bash
make test-rules
```

Expected: `SUCCESS`.

```bash
make lint-config
```

Expected: `SUCCESS` lines for the rules file and both configuration files.

```bash
curl -s "http://127.0.0.1:29090/api/v1/status/tsdb?limit=5" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['headStats']['numSeries'], [(x['name'], x['value']) for x in d['labelValueCountByLabelName'][:3]])"
```

Expected (needs `make up`): about 1,800 series and the three labels with the most values (no `user_id`).

```bash
curl -s "http://127.0.0.1:29090/api/v1/rules" | python3 -c "import json,sys; print([r['name'] for g in json.load(sys.stdin)['data']['groups'] for r in g['rules']])"
```

Expected: `['AppSeriesBudgetExceeded', 'PrometheusHeadSeriesHigh', 'MetricLabelGuardTriggered']`.

```bash
diff observability/prometheus/prometheus.yml observability/prometheus/prometheus.guarded.yml
```

Expected: only the header comment lines and the `metric_relabel_configs` block (the lines the guard adds).

```bash
make run USERS=5000 REQUESTS=20000
```

Expected (needs `make up`; about ten minutes): the report from `python.md` (the series count rising about 75-fold, then returning, the guarded state, and the slow tenant found from traces).

## Mistakes people make

- **High-cardinality labels.** Every distinct label value creates a series. Never label by user id or order id.
- **Using `rate()` on a gauge** or `avg()` of a quantile.
- **Too short a range in `rate(x[30s])`** with a scrape interval close to it: needs at least two samples inside the range.
- **Trusting the p95 of a barely loaded system.** One slow request out of twenty sits right on the p95 edge; a ratio like "share slower than 1 s" is steadier.
- **Reloading a bad config.** Run `promtool check config` first. `make lint-config` does.

## Check yourself

1. Does Prometheus receive data or fetch it? *It fetches (scrapes) it.*
2. What is a time series? *A metric name plus a set of labels, with its points over time.*
3. What are the three series a histogram makes? *`_bucket` (with `le`), `_sum` and `_count`.*
4. What does `for: 1m` mean on an alert? *The expression must be true continuously for one minute before the alert fires.*
5. What does `promtool test rules` need that a real Prometheus supplies in production? *Nothing; you give it fake input series.*

## Further reading

- Prometheus v2.54 documentation: https://prometheus.io/docs/prometheus/2.54/
- Configuration: https://prometheus.io/docs/prometheus/2.54/configuration/configuration/
- Alerting rules: https://prometheus.io/docs/prometheus/2.54/configuration/alerting_rules/
- Unit testing for rules: https://prometheus.io/docs/prometheus/2.54/configuration/unit_testing_rules/
- Metric types: https://prometheus.io/docs/concepts/metric_types/
- Exemplars: https://prometheus.io/docs/prometheus/2.54/feature_flags/#exemplars-storage
- OpenMetrics: https://prometheus.io/docs/instrumenting/exposition_formats/#openmetrics-text-format
