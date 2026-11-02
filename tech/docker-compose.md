# Docker Compose

## What it is

Docker Compose is a tool that starts several containers together from one file. The file is usually named `docker-compose.yml`. In it you list **services** (each service is one container definition: which image, which command, which environment variables, which ports, which volumes), and Compose creates a private network for them, starts them in the right order, and lets you stop them all with one command.

This repository uses **Compose v2**, which you run as `docker compose` (with a space). It is part of the Docker command-line program. The older v1 was a separate program called `docker-compose` with a hyphen.

## Why this repository uses it

The scenario has to *change the running stack on purpose*: restart the app with the user label on, swap Prometheus's configuration, throw Prometheus's database away. Compose makes that possible because almost every setting in the file is an environment variable with a safe default (`${NAME:-default}`). The scenario sets the variables and runs `docker compose up` again; no file is edited.

## Where it appears

| Path | What it does |
| --- | --- |
| `docker-compose.yml` | The five services (app, Collector, Tempo, Prometheus, Grafana) and three volumes. |
| `src/cardinality_lab/lab/compose.py` | Runs `docker compose` with different environments (see `python-subprocess.md`). |
| `Makefile` | `up` and `down`. |
| `tests/observability/test_configuration_as_code.py` | Lints the file. |

## How it works underneath

`docker compose up` reads the YAML file, resolves `${VARIABLE}` placeholders from your shell and from a file named `.env` in the same folder, and builds a plan. For every service it creates a container. For the whole project it creates one **network**. Each container joins the network under its service name, and Docker runs a small DNS server on that network. So the container `back` can call `http://postgres:5432` and the name `postgres` resolves to the database container's address. These names only exist inside the network.

A **published port** (`"127.0.0.1:23000:3000"`) opens a door from your machine into a container: connections to port 23000 on your machine's own loopback address are forwarded to port 3000 inside the container. Without the `127.0.0.1:` part, Docker would listen on every network interface and other computers could connect.

`depends_on` with `condition: service_healthy` makes Compose wait until the other service's health check passes before starting this one. `--wait` makes `docker compose up` itself wait until all started services are healthy (or running, when they have no health check).

A **named volume** listed at the bottom of the file is created once and kept between runs. `docker compose down -v` stops the containers, removes them and the network, and deletes the named volumes.

A **project name** (the `name:` key, or the folder name by default) is a prefix Compose puts on every container, network and volume it creates, so two projects do not clash.

## Walkthrough of this repository's use

### The header

```yaml
# The lab on one laptop: the checkout app, a real Prometheus, a Collector and Tempo for traces, and Grafana.
# Every host port is bound to 127.0.0.1 only. The scenario (make run) recreates the app and Prometheus with different
# settings through the variables below, so their defaults here are the safe, baseline state.
name: observability-cardinality-blowup
```

The comments say what runs and the two rules (ports on `127.0.0.1` only; the defaults are the safe baseline). `name:` is the project name, used as a prefix for containers, the network and the volumes (for example `observability-cardinality-blowup_prometheus-data`).

### `app`

```yaml
services:
  app:
    build: .
    image: observability-cardinality-blowup:dev
    command: ["opentelemetry-instrument", "cardinality-lab-app"]
    environment:
      BIND_HOST: 0.0.0.0
      APP_PORT: "8080"
      METRICS_PORT: "9100"
```

`build: .` builds the image from the `Dockerfile` here and `image:` names the result. `command` overrides the image's default. The `environment` mapping starts with the bind address `0.0.0.0` (all interfaces inside the container) and the two ports: the app on 8080, the metrics page on 9100.

```yaml
      # The lesson's mistake as a switch. false = route, method, status. true = also user_id.
      METRICS_INCLUDE_USER_ID: ${METRICS_INCLUDE_USER_ID:-false}
      # The slow dependency: slow only when the route AND this tenant match. Empty = off.
      SLOW_TENANT: ${SLOW_TENANT:-}
      SLOW_SECONDS: ${SLOW_SECONDS:-2.0}
      SEED: ${SEED:-2026}
```

The experiment's switches. `METRICS_INCLUDE_USER_ID: ${METRICS_INCLUDE_USER_ID:-false}` means: use the variable from the environment, or `false` if unset or empty. The scenario sets it to `true` for the blow-up phases. `SLOW_TENANT: ${SLOW_TENANT:-}` is empty by default (the slow rule off). `SLOW_SECONDS` defaults to 2.0 and `SEED` to 2026. The comments in the file explain each. A test checks that the defaults in the file are the safe ones.

```yaml
      OTEL_SERVICE_NAME: checkout
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318
      OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf
      OTEL_TRACES_EXPORTER: otlp
      OTEL_METRICS_EXPORTER: none
      OTEL_LOGS_EXPORTER: none
      OTEL_PYTHON_FLASK_EXCLUDED_URLS: healthz
      LOG_LEVEL: WARNING
```

The OpenTelemetry settings (see `opentelemetry.md`): traces on, metrics and logs off. `LOG_LEVEL: WARNING` keeps the log quiet during hundreds of thousands of requests.

```yaml
    ports:
      - "127.0.0.1:${APP_HOST_PORT:-28082}:8080"
    depends_on:
      otel-collector: { condition: service_started }
    healthcheck:
      test: ["CMD", "cardinality-lab-health", "--url", "http://localhost:8080/healthz", "--timeout", "10"]
      interval: 10s
      timeout: 20s
      retries: 30
      start_period: 60s
    stop_grace_period: 15s
```

`ports: "127.0.0.1:${APP_HOST_PORT:-28082}:8080"`: host port 28082 on the loopback address maps to the app's 8080. The metrics port 9100 is **not** published; Prometheus reaches it as `app:9100` inside the network. `depends_on` has the Collector `service_started`. The health check runs the app's own probe `cardinality-lab-health` (exec form, no shell) against `http://localhost:8080/healthz`; interval 10 s, timeout 20 s, 30 retries and a 60 s start period are generous for a busy machine. `stop_grace_period: 15s` gives the app 15 seconds to finish requests after `SIGTERM`.

### `otel-collector`, `tempo`, `prometheus`, `grafana`

```yaml
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.111.0
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./observability/collector/config.yaml:/etc/otelcol/config.yaml:ro
    depends_on:
      tempo: { condition: service_healthy }

  tempo:
    image: grafana/tempo:2.6.1
    command: ["-config.file=/etc/tempo/tempo.yaml"]
    volumes:
      - ./observability/tempo/tempo.yaml:/etc/tempo/tempo.yaml:ro
      - tempo-data:/var/tempo
    ports:
      - "127.0.0.1:${TEMPO_HOST_PORT:-23200}:3200"
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O - http://localhost:3200/ready | grep -q ready"]
      interval: 10s
      timeout: 10s
      retries: 60
      start_period: 30s
```

The Collector (config mounted read-only, waits for Tempo to be healthy) and Tempo (config, data volume, port 23200, health check): see `opentelemetry-collector.md` and `tempo.md`.

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

Prometheus: see `prometheus.md`. Note the configuration mount `${PROMETHEUS_CONFIG:-./observability/prometheus/prometheus.yml}:/etc/prometheus/prometheus.yml:ro` and `mem_limit: 3g`.

```yaml
  grafana:
    image: grafana/grafana:11.2.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?run make up, which creates .env from .env.example}
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./observability/grafana/dashboards:/etc/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    ports:
      - "127.0.0.1:${GRAFANA_HOST_PORT:-23000}:3000"
    depends_on:
      tempo: { condition: service_healthy }
      prometheus: { condition: service_healthy }
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O - http://localhost:3000/api/health | grep -q ok"]
      interval: 10s
      timeout: 10s
      retries: 60
      start_period: 30s

volumes:
  tempo-data:
  prometheus-data:
  grafana-data:
```

Grafana and the three named volumes `tempo-data`, `prometheus-data` and `grafana-data`: see `grafana.md`.

### How the scenario uses it

`recreate_app` sets three variables and runs `docker compose up -d --force-recreate --no-deps --wait app`. Compose re-reads the file with the new environment, sees a different configuration for `app`, recreates its container and waits for the health check. `reset_prometheus` runs `rm -sf prometheus`, deletes the volume and starts a new Prometheus with the chosen `PROMETHEUS_CONFIG`. See `python-subprocess.md`.

```makefile
up: .env $(STAMP) ## build and start the app, Prometheus, the Collector, Tempo and Grafana
	docker compose up -d --build --wait --wait-timeout 1800
	$(MAKE) --no-print-directory health
```

`make up` runs `docker compose up -d --build --wait --wait-timeout 1800` (build, start everything in the background, wait up to thirty minutes for all health checks) and then `make health`.

```makefile
down: ## stop the stack and delete its data
	docker compose down -v
```

`make down` runs `docker compose down -v`: stop and remove the containers and the network, and delete the volumes.

## Try it yourself

```bash
docker compose config --quiet && echo valid
```

Expected: `valid` (needs `.env`, which `make up` creates).

```bash
docker compose ps
```

Expected (after `make up`): `app`, `otel-collector`, `tempo`, `prometheus` and `grafana`; all healthy except the Collector, which has no health check and shows `running`.

```bash
METRICS_INCLUDE_USER_ID=true docker compose config | grep METRICS_INCLUDE
```

Expected: `METRICS_INCLUDE_USER_ID: "true"`: the shell variable overrides the default without touching the file.

```bash
docker compose config | grep -E "mem_limit|published"
```

Expected: the 3 GB limit (as bytes) and each published port with `host_ip: 127.0.0.1`.

```bash
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep prometheus
```

Expected: Prometheus's memory use against its 3 GiB limit.

## Mistakes people make

- **Expecting `depends_on` to wait for readiness.** The short form only waits for the container to *start*. Use `condition: service_healthy` together with a health check.
- **Publishing a port on every interface.** `"3000:3000"` listens on all interfaces. Prefix `127.0.0.1:` unless other machines must connect.
- **Putting secrets in the YAML.** Keep them in `.env` (which is git-ignored) and reference them as `${NAME}`. This repository uses `${NAME:?message}` so Compose stops with a clear message when a required variable is missing.
- **Forgetting `-v` on `down`.** Without it the volumes survive, and a later `up` starts with the old data. Sometimes that is wanted; for a repeatable lab it is not.
- **Using `localhost` between containers.** Use the service name.
- **Reading the YAML indentation wrongly.** One space too many silently makes a key belong to another block. Lint the file (`docker compose config` prints the final, resolved version).

## Check yourself

1. How does one container find another by name? *Compose puts all services on one network with a DNS server; the service name resolves to that container's address.*
2. What does `127.0.0.1:23000:3000` mean? *Port 3000 inside the container is reachable only from your own machine, on port 23000.*
3. What is the difference between `depends_on: [db]` and `depends_on: {db: {condition: service_healthy}}`? *The first waits for the container to start; the second waits until its health check passes.*
4. What does `docker compose down -v` delete that `docker compose down` keeps? *The named volumes, and so the data stored in them.*
5. What does `${NAME:?text}` do when `NAME` is empty or unset? *Compose stops and prints the text as an error.*

## Further reading

- Compose file reference: https://docs.docker.com/reference/compose-file/
- `docker compose up`: https://docs.docker.com/reference/cli/docker/compose/up/
- Compose networking: https://docs.docker.com/compose/how-tos/networking/
- Variable interpolation: https://docs.docker.com/reference/compose-file/interpolation/
