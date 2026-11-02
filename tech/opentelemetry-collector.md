# OpenTelemetry Collector (contrib 0.111.0)

## What it is

The OpenTelemetry Collector is a standalone program that receives telemetry, changes it, and sends it on. Applications send OTLP to the Collector at one address, and the Collector decides where each signal goes. That keeps the applications simple and lets you change backends without changing code. Its configuration is one YAML file with four kinds of building blocks:

- **receivers** accept data (for example `otlp`, which listens for OTLP over gRPC on port 4317 and over HTTP on port 4318);
- **processors** change data on the way (batch it, limit memory, drop or rewrite attributes);
- **exporters** send data out (to Tempo, Prometheus, Loki);
- **extensions** add side features that are not in the data path (a health check endpoint).

You choose the image `otel/opentelemetry-collector-contrib`, the distribution that includes the community components. This repository pins version 0.111.0.

## Why this repository uses it

Traces need a receiver in front of Tempo. The app sends OTLP over HTTP to the Collector, and the Collector batches the spans and forwards them to Tempo over gRPC. The Collector in this lab handles **traces only**. The metrics do not pass through it, which is why the cardinality guard lives in Prometheus's scrape configuration and not here (decision record `docs/adr/0002-guard-in-the-scrape-config-not-the-collector.md`).

## Where it appears

| Path | What it does |
| --- | --- |
| `observability/collector/config.yaml` | The whole Collector configuration. |
| `docker-compose.yml` (service `otel-collector`) | Runs the pinned image with that file mounted read-only. |
| `Makefile` (`lint-config`) | Validates the file with the Collector's own `validate` command. |
| `tests/observability/test_configuration_as_code.py` | Checks the traces pipeline has `memory_limiter` first and `batch` last. |

## How it works underneath

Defining a component under `receivers:` or `exporters:` does **not** turn it on. Only components listed in `service.pipelines` run. A **pipeline** is a signal type (`traces`, `metrics` or `logs`) plus an ordered list of receivers, processors and exporters. Data enters from the receivers, passes through each processor in the written order, and is sent to every exporter.

Names can have a suffix after a slash (`otlp/tempo`, `otlphttp/loki`): the part before the slash is the component type, and the part after is a label so you can define the same type twice.

Inside the process, each pipeline is a chain of queues and workers. The `memory_limiter` processor checks memory use every `check_interval`. When use crosses the soft limit (`limit_mib` minus `spike_limit_mib`) it starts refusing new data, which tells the sender to retry later; this prevents the Linux out-of-memory killer from stopping the process. The `batch` processor collects items and sends them when `send_batch_size` is reached or `timeout` passes, so the backend gets a few big requests, not thousands of small ones.

The Collector also reports on itself: its own logs and metrics (`service.telemetry`), and a `health_check` extension that answers HTTP 200 on port 13133 when the process is running. The image has no shell or `wget`, so Docker cannot run a health-check command inside it; other tools call the extension from outside.

## Walkthrough of this repository's use

### `observability/collector/config.yaml`

```yaml
# Traces only: the metrics go straight from the app's client library to Prometheus, which is why the cardinality
# guard lives in Prometheus's scrape config (see docs/adr/0002).
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
```

The comment states the design. The only receiver is `otlp`, with only the HTTP protocol on `0.0.0.0:4318` (all interfaces inside the container, so the app container can reach it). There is no gRPC receiver and no published host port: only containers on the Compose network talk to the Collector.

```yaml
processors:
  # First in the pipeline: refuse data instead of being killed by the out-of-memory killer.
  memory_limiter:
    check_interval: 1s
    limit_mib: 384
    spike_limit_mib: 96
  batch:
    timeout: 1s
    send_batch_size: 1024
```

`memory_limiter` is first in the pipeline: every second it measures memory; at a hard limit of 384 MiB (soft limit 384 − 96 = 288 MiB) it refuses new data so the process is not killed by the operating system. `batch` sends 1,024 spans at a time or after one second, whichever comes first.

```yaml
exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
```

`otlp/tempo` exports over OTLP gRPC to `tempo:4317`, with TLS switched off (`insecure: true`): fine between two containers on a private network.

```yaml
service:
  telemetry:
    logs:
      level: warn
    metrics:
      level: none
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
```

`service.telemetry` configures the Collector's own diagnostics: logs at `warn` and metrics at level `none` (the Collector's own metrics are not collected in this lab). There is a single pipeline, `traces`, wiring `otlp` through `memory_limiter` and `batch` to `otlp/tempo`. There is no `extensions` block here, so the Collector has no health endpoint; Compose only waits for it to start (`condition: service_started`), and Tempo's health decides when the pipeline is useful.

### The Compose service and the Makefile check

```yaml
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.111.0
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./observability/collector/config.yaml:/etc/otelcol/config.yaml:ro
    depends_on:
      tempo: { condition: service_healthy }
```

The pinned image `otel/opentelemetry-collector-contrib:0.111.0`, the `--config` flag, the config mounted read-only, and `depends_on` Tempo being healthy so the Collector does not start exporting to a Tempo that is not ready. It publishes no ports: the app reaches it as `otel-collector:4318` on the Compose network.

```makefile
	docker run --rm -v "$(CURDIR)/observability/collector/config.yaml:/etc/otelcol/config.yaml:ro" $(COLLECTOR_IMAGE) \
	  validate --config=/etc/otelcol/config.yaml
```

`lint-config` runs the Collector image once with `validate --config=...`, which checks the file and every component name, and exits non-zero on a problem. See `make.md`.

## Try it yourself

```bash
docker run --rm -v "$PWD/observability/collector/config.yaml:/etc/otelcol/config.yaml:ro" otel/opentelemetry-collector-contrib:0.111.0 validate --config=/etc/otelcol/config.yaml; echo "exit $?"
```

Expected: `exit 0`.

```bash
docker compose logs otel-collector | tail -3
```

Expected (needs `make up`): start-up lines; at the `warn` level the log is nearly empty while all is well.

```bash
docker compose exec app python -c "import urllib.request as u; print(u.urlopen('http://otel-collector:4318/').status)"
```

Expected: an HTTP error (404 or 405) is raised, which proves the receiver is listening: the OTLP paths are `/v1/traces` and the others.

```bash
.venv/bin/python -m pytest tests/observability -k collector -q
```

Expected: `1 passed`.

```bash
grep -n "pipelines" -A4 observability/collector/config.yaml
```

Expected: the single `traces` pipeline.

## Mistakes people make

- **Defining a component but not adding it to a pipeline.** It then does nothing and no error is shown.
- **Wrong processor order.** `memory_limiter` must be first, `batch` last.
- **Using `localhost` as an exporter endpoint** inside a container. Use the service name.
- **Forgetting `tls: insecure: true`** for a plain-text local gRPC endpoint.
- **Using a deprecated exporter.** The `loki` exporter is deprecated for logs in 0.111.0; this repository sends logs to Loki's native OTLP endpoint with `otlphttp`.

## Check yourself

1. What are the four kinds of Collector components? *Receivers, processors, exporters and extensions.*
2. What makes a defined component actually run? *Listing it in a pipeline (extensions: under `service.extensions`).*
3. Why is `memory_limiter` first? *So it can refuse data before the other processors use more memory.*
4. What does `batch` do? *It groups items into larger requests, sent by size or timeout.*
5. Why does `otlp/tempo` have a slash? *The suffix lets you define several components of the same type.*

## Further reading

- Collector documentation: https://opentelemetry.io/docs/collector/
- Configuration: https://opentelemetry.io/docs/collector/configuration/
- Components list (contrib v0.111.0): https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.111.0
- `memory_limiter` processor: https://github.com/open-telemetry/opentelemetry-collector/tree/v0.111.0/processor/memorylimiterprocessor
- `batch` processor: https://github.com/open-telemetry/opentelemetry-collector/tree/v0.111.0/processor/batchprocessor
