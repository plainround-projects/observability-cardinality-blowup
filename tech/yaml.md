# YAML

## What it is

YAML is a text format for configuration data. It describes the same things as JSON (key/value maps, lists, strings, numbers, true/false, null) but uses **indentation** and dashes instead of braces and brackets, and allows `#` comments. Every Compose file, Prometheus configuration, Collector configuration, Grafana provisioning file, alert rule file and GitHub workflow in this repository is YAML.

## Why this repository uses it

Everything that configures the stack is YAML, so a learner meets the format in ten files. The lesson's central artefact, the Prometheus guard, is five lines of YAML: reading it correctly matters.

## Where it appears

| Path | What it configures |
| --- | --- |
| `docker-compose.yml` | The containers. |
| `observability/collector/config.yaml` | The Collector. |
| `observability/tempo/tempo.yaml` | Tempo. |
| `observability/prometheus/prometheus.yml`, `prometheus.guarded.yml`, `rules/cardinality.rules.yml`, `tests/cardinality.rules.test.yml` | Prometheus (baseline and guarded), its alerts and their tests. |
| `observability/grafana/provisioning/**/*.yaml` | Grafana data sources and the dashboard loader. |
| `.github/workflows/ci.yml` | The CI workflow. |
| `tests/observability/test_configuration_as_code.py` | Reads the files with PyYAML. |

## How it works underneath

- A **mapping** is a set of `key: value` lines at the same indentation. Indentation must use spaces, never tabs.
- A **sequence** (list) is a series of lines that start with `- `. A list item that is a mapping puts its first key on the dash line and the next keys aligned under it.
- A **flow** style is allowed for short values: `[a, b]` for a list and `{k: v}` for a mapping.
- Scalars (single values) can be unquoted (`22`, `true`, `ticket`), or quoted. A value like `"5000"` in quotes is a string, while `5000` is a number. Unquoted `yes`, `no`, `on`, `off` can be read as booleans by some parsers; quote them when you mean text.
- A multi-line string uses `|` (keep line breaks) or `>` (join lines). Prometheus alert expressions use `|`.
- **Anchors and merge keys.** `&name` marks a block so it can be reused; `*name` copies it; `<<: *name` merges the copied mapping into the current one. Compose files use it to share environment variables.
- A file can hold several documents separated by `---`. Not used here.

The parser turns the text into the same structures a program would build in memory (maps and lists), and the program then reads keys from them. The `tests/observability` tests use PyYAML's `safe_load` to do exactly that.

## Walkthrough of this repository's use

Each file is explained in its own note. This note shows the YAML features used and where.

**Mappings, nesting and a list of mappings.** The Prometheus scrape configuration is the most nested file:

```yaml
scrape_configs:
  - job_name: checkout
    # A blown-up app serves tens of megabytes per scrape; give it time and a longer interval.
    scrape_interval: 60s
    scrape_timeout: 55s
    static_configs:
      - targets: ["app:9100"]
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

`scrape_configs:` is a list (each item starts with `- `). The first item is a mapping: `job_name`, `scrape_interval`, `scrape_timeout`, `static_configs` (a list holding a mapping that has `targets`, a list written in flow style on one line), and `metric_relabel_configs` (a list of mappings with `action` and `regex`). Indentation shows which key belongs to which: `regex: user_id` lines up with `action: labeldrop` because both belong to the same list item.

**Flow style.** Short lists and maps can sit on one line:

```yaml
    depends_on:
      otel-collector: { condition: service_started }
```

`otel-collector: { condition: service_started }` is a mapping with one key.

```yaml
      test: ["CMD", "cardinality-lab-health", "--url", "http://localhost:8080/healthz", "--timeout", "10"]
```

`test: ["CMD", "cardinality-lab-health", ...]` is a list on one line; Compose runs it without a shell.

**Quoting.** Environment values must be text, so numbers are quoted:

```yaml
      BIND_HOST: 0.0.0.0
      APP_PORT: "8080"
      METRICS_PORT: "9100"
```

`APP_PORT: "8080"` is the string `8080`. A port mapping is quoted too:

```yaml
      - "127.0.0.1:${APP_HOST_PORT:-28082}:8080"
```

so the colons are not misread. Unquoted `${METRICS_INCLUDE_USER_ID:-false}` is fine: a value starting with `$` is plain text to YAML, and Compose substitutes it later.

**Strings inside strings.** A promtool test series is a YAML string that contains a PromQL selector with its own quotes:

```yaml
      - series: 'scrape_samples_post_metric_relabeling{job="checkout"}'
        values: "75x40"
      - series: "prometheus_tsdb_head_series"
        values: "1842x40"
      - series: 'prometheus_target_scrapes_sample_duplicate_timestamp_total{}'
        values: "0x40"
```

Single quotes outside, double quotes inside. The `values` strings use promtool's own mini-language (`75x40` means 75 repeated 40 times), which is text to YAML.

**Comments** (`#`) explain the *why* in every file, for example the comment above the guard rule.

**Reading it from code.** The configuration test loads files with `yaml.safe_load`, which returns dicts and lists:

```python
def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())
```

`safe_load` refuses to build arbitrary Python objects, which is why you use it on files and never `yaml.load` on files you did not write.

## Try it yourself

```bash
.venv/bin/python -c "import yaml; print(yaml.safe_load(open('observability/prometheus/prometheus.guarded.yml'))['scrape_configs'][0]['metric_relabel_configs'])"
```

Expected: `[{'action': 'labeldrop', 'regex': 'user_id'}]`.

```bash
docker compose config | sed -n 1,20p
```

Expected: the Compose file with variables substituted: `METRICS_INCLUDE_USER_ID: "false"` and `APP_PORT: "8080"`.

```bash
.venv/bin/python -c "import yaml; print(yaml.safe_load('a: \"5000\"\nb: 5000'))"
```

Expected: `{'a': '5000', 'b': 5000}`: the quoted value is text, the other a number.

```bash
.venv/bin/python -c "import yaml; yaml.safe_load('a:\n\tb: 1')"
```

Expected: a `ScannerError` about the tab character: tabs are not allowed.

```bash
.venv/bin/python -m pytest tests/observability -q
```

Expected: all pass.

## Mistakes people make

- **Tabs.** YAML forbids them for indentation.
- **Wrong indentation level** quietly moves a key to a different parent.
- **Unquoted special characters.** A value containing `: ` or starting with `{`, `*` or `&` must be quoted.
- **Numbers that should be strings.** A port mapping like `"127.0.0.1:23000:3000"` must be quoted, or some parsers read `22:22` as a sexagesimal number.
- **Duplicate keys**, where the last one silently wins.

## Check yourself

1. How does YAML show that one key is inside another? *By indenting it further with spaces.*
2. What is the difference between `5000` and `"5000"`? *The first is a number; the second is a string.*
3. What does `<<: *service-environment` do? *It copies the anchored mapping's keys into this mapping.*
4. Can you indent YAML with tabs? *No.*
5. What does `|` after a key mean? *The following indented lines are one multi-line string with line breaks kept.*

## Further reading

- YAML 1.2 specification: https://yaml.org/spec/1.2.2/
- PyYAML documentation: https://pyyaml.org/wiki/PyYAMLDocumentation
