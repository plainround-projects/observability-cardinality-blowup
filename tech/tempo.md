# Tempo (2.6.1)

## What it is

Tempo is a database for **traces** made by Grafana Labs. It accepts spans (here, over OTLP gRPC from the Collector), stores them cheaply in blocks on disk, and answers two kinds of question: "give me the trace with this id" and "find traces matching this condition" in a query language called **TraceQL**. This repository pins Tempo 2.6.1 and runs it as one process ("single binary") with its data on a local volume. That is enough for a laptop; a production Tempo is split into several services.

## Why this repository uses it

Tempo is where the per-user detail goes after the fix. A metric cannot afford a user id, but a trace can carry one for free: Tempo stores each span once and searches attributes on demand. The lesson proves it twice: all requests of one busy user are found by `user.id`, and the one slow tenant (under one percent of traffic, invisible in the route's p95) is found with a TraceQL query on tenant, route and duration.

## Where it appears

| Path | What it does |
| --- | --- |
| `observability/tempo/tempo.yaml` | Tempo's configuration (a single-binary Tempo with local storage). |
| `docker-compose.yml` (service `tempo`) | The pinned image, config, data volume, port 23200 and health check. |
| `observability/collector/config.yaml` | The exporter that sends spans here (see `opentelemetry-collector.md`). |
| `observability/grafana/provisioning/datasources/datasources.yaml` | The Tempo data source. |
| `src/cardinality_lab/lab/tempo.py` | `TempoClient`: tag search and TraceQL search (see `requests.md`). |
| `observability/grafana/dashboards/cardinality-blowup.json` | Panel 10: slow traces of one tenant. |

## How it works underneath

Tempo's pieces, all inside one process here: the **distributor** receives spans and hashes the trace id to choose an ingester; the **ingester** holds recent spans in memory and in a write-ahead log (`wal`, a file where every write is recorded first, so a crash loses nothing), and cuts a **block** after `max_block_duration`; the **compactor** merges small blocks and deletes blocks older than `block_retention`; the **querier** reads blocks and the ingester to answer queries.

A trace arrives in pieces, because each service exports its own spans separately. Tempo can therefore return a **partial trace** for a few seconds: for example the back service's spans without the front service's root span. Tools that need a whole trace (the `wait_for_trace` helper here) check that every span's parent is present.

TraceQL looks like `{ resource.service.name = "back" && duration > 1s }`. Braces hold conditions on one span; `resource.` reads attributes of the resource (the process), `span.` reads span attributes, `duration` is the span's length. The API `/api/search?q=...` runs TraceQL; `/api/traces/<id>` fetches one trace; `/ready` says whether Tempo is ready.

## Walkthrough of this repository's use

### `tempo.yaml`

```yaml
# Single-binary Tempo with local storage: enough for a laptop, not a production topology.
stream_over_http_enabled: true
server:
  http_listen_port: 3200
  log_level: warn
```

The comment says what this is. `stream_over_http_enabled: true` allows streaming search results. `server` sets the HTTP port to 3200 (the API and `/ready`) and quiet logs.

```yaml
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
```

The `distributor` receives spans from the Collector over OTLP gRPC on port 4317 inside the container.

```yaml
ingester:
  max_block_duration: 2m

compactor:
  compaction:
    block_retention: 24h
```

The `ingester` cuts a block of recent traces every two minutes, so traces become searchable from storage soon; the `compactor` deletes blocks older than 24 hours.

```yaml
storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks

usage_report:
  reporting_enabled: false
```

Storage is `local`: the write-ahead log in `/var/tempo/wal` and blocks in `/var/tempo/blocks`, on the `tempo-data` volume. `usage_report` is switched off so Tempo sends no statistics.

### The Compose service

```yaml
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

The `-config.file` flag, the read-only mounted config, the data volume, port 3200 published as 23200 on the loopback address, and a health check that fetches `/ready` and looks for the word `ready`.

### The two searches the lesson uses

```python
    def search_by_tags(self, tags: Mapping[str, str], start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces having every ``key=value`` tag, in the time range (the lesson's ``/api/search?tags=`` call)."""
        encoded = " ".join(f"{key}={value}" for key, value in tags.items())
        return self._search({"tags": encoded, "start": int(start), "end": int(end) + 1, "limit": limit})

    def search_traceql(self, query: str, start: float, end: float, limit: int = 1000) -> list[TraceHit]:
        """Traces matching a TraceQL query in the time range."""
        return self._search({"q": query, "start": int(start), "end": int(end) + 1, "limit": limit})
```

`search_by_tags` calls `/api/search?tags=user.id=user-000007`: the **tag search**. A tag is a span or resource attribute; the value is matched exactly. This is the lesson's "find all requests of one user".

`search_traceql` sends a **TraceQL** query. The scenario's query is

```python
        self._compose.recreate_app(include_user_id=False, slow_tenant=SLOW_TENANT, prometheus_config=GUARDED_CONFIG)
        after_load = self._traffic(plan.slow_phase_requests, 5)
        self._settle()
```

`{ ... }` selects spans. `name = "checkout"` matches the span's name; `span.tenant.id = "tenant-0007"` and `span.route = "checkout"` match span attributes (`span.` is the prefix for span-level attributes); `&&` is "and"; `duration > 1s` keeps spans longer than a second. So it finds the checkout spans of the slow tenant that took more than one second: exactly the requests the p95 hid.

## Try it yourself

```bash
curl -s http://127.0.0.1:23200/ready
```

Expected (needs `make up`): `ready`.

```bash
curl -s -H "X-User-Id: user-424242" -H "X-Tenant-Id: tenant-0004" -o /dev/null http://127.0.0.1:28082/checkout; sleep 8; curl -s --get "http://127.0.0.1:23200/api/search" --data-urlencode 'tags=user.id=user-424242' | python3 -c "import json,sys; print(len(json.load(sys.stdin)['traces']))"
```

Expected: `1`.

```bash
curl -s --get "http://127.0.0.1:23200/api/search" --data-urlencode 'q={ name = "checkout" && duration > 1ms }' --data-urlencode 'limit=3' | python3 -m json.tool | head -15
```

Expected: up to three recent traces (checkout spans longer than a millisecond, if any).

```bash
.venv/bin/python -m pytest tests/integration -k findable -q
```

Expected (needs `make up`): `1 passed`: one request leaves exactly one trace, findable by its user id.

```bash
docker compose exec tempo ls /var/tempo
```

Expected: `wal`, and `blocks` after the first block is cut.

## Mistakes people make

- **Looking for the trace immediately.** Spans take seconds to flush and index.
- **Treating a partial trace as the whole.** Check that every parent exists.
- **Running the single binary in production.** It is for learning.
- **Forgetting that ids may be base64 or hex** depending on the API; the client here normalizes.

## Check yourself

1. What does Tempo store? *Traces (spans).*
2. What does the WAL protect? *Recent spans that are not yet in a block, in case of a crash.*
3. Why might a trace look incomplete right after the request? *The services export spans separately and Tempo receives them at slightly different times.*
4. What does `{ duration > 1s }` select? *Spans longer than one second.*
5. Which endpoint tells you Tempo is ready? *`/ready`.*

## Further reading

- Tempo 2.6 documentation: https://grafana.com/docs/tempo/v2.6.x/
- Configuration: https://grafana.com/docs/tempo/v2.6.x/configuration/
- TraceQL: https://grafana.com/docs/tempo/v2.6.x/traceql/
- HTTP API: https://grafana.com/docs/tempo/v2.6.x/api_docs/
