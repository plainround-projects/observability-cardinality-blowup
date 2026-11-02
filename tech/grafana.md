# Grafana (11.2.0)

## What it is

Grafana is a web application that draws dashboards from data stores. It stores no telemetry itself. You connect **data sources** (Prometheus, Tempo, Loki), and each dashboard **panel** runs a query against one data source and draws the result as a graph, a table or a list of log lines. Grafana can also link data sources: a click on an exemplar dot opens a trace in Tempo; a click on "logs for this span" runs a Loki query. This repository pins Grafana 11.2.0.

## Why this repository uses it

The lesson asks the learner to see the problem, not only read numbers. The dashboard puts the number of active series, Prometheus's memory, the samples per scrape and the cost of the dashboard query on one screen, so the blow-up is visible as it happens, plus a TraceQL table that shows the slow tenant that the p95 line hides.

## Where it appears

| Path | What it does |
| --- | --- |
| `observability/grafana/provisioning/datasources/datasources.yaml` | Creates the Prometheus and Tempo data sources. |
| `observability/grafana/provisioning/dashboards/dashboards.yaml` | Tells Grafana to load dashboards from a folder. |
| `observability/grafana/dashboards/cardinality-blowup.json` | The dashboard: ten panels. |
| `docker-compose.yml` (service `grafana`) | The pinned image, mounts, admin password, health check. |
| `src/cardinality_lab/lab/health_cli.py` | Asks Grafana to query both data sources. |
| `tests/observability/test_configuration_as_code.py` | Lints the data sources and the dashboard. |

## How it works underneath

Grafana runs as one server process with a built-in web UI, a small database (SQLite in `/var/lib/grafana`) for its own settings, and an HTTP API. The browser sends requests to the Grafana server, and the server forwards the queries to the data sources (`access: proxy`), so the browser never needs to reach Prometheus directly.

**Provisioning** means Grafana reads YAML files from `/etc/grafana/provisioning` at start and creates data sources and dashboard providers from them, instead of someone clicking in the UI. A **dashboard provider** tells Grafana a folder where it should load dashboard JSON files. The result is the same on every start, and everything is code that can be reviewed.

Settings can come from environment variables named `GF_<SECTION>_<KEY>` (for example `GF_SECURITY_ADMIN_PASSWORD`).

A dashboard JSON has a `uid` (its stable id), a list of `panels`, each with a `gridPos` (x, y, width, height on a 24-column grid), `targets` (the queries), and display options. `schemaVersion` records the structure version Grafana expects.

Grafana's data-source API: `GET /api/datasources/uid/<uid>/health` asks a data source to test itself, and `GET /api/datasources/proxy/uid/<uid>/<path>` passes a request through to that data source.

## Walkthrough of this repository's use

### `datasources.yaml`

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    uid: prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      httpMethod: POST

  - name: Tempo
    uid: tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    jsonData:
      nodeGraph:
        enabled: false
```

`apiVersion: 1` is the provisioning format. **Prometheus**: `uid: prometheus` is the stable id the dashboard uses; `access: proxy` means Grafana's server makes the queries; `url: http://prometheus:9090` is the address inside the Compose network; `isDefault: true`; `httpMethod: POST` sends queries in the body so long expressions fit. **Tempo**: `uid: tempo` and `url: http://tempo:3200`; `nodeGraph.enabled: false` turns off the service-graph view (this lab has one service). Unlike `observability-three-signals`, there are no links between the data sources: no logs and no exemplars here.

### `dashboards.yaml`

```yaml
apiVersion: 1

providers:
  - name: cardinality-blowup
    type: file
    disableDeletion: true
    allowUiUpdates: false
    options:
      path: /etc/grafana/dashboards
```

A dashboard provider named `cardinality-blowup` reads JSON from `/etc/grafana/dashboards`. `disableDeletion: true` and `allowUiUpdates: false` keep the dashboard exactly as in the repository.

### `cardinality-blowup.json`: the dashboard

```json
{
  "uid": "cardinality-blowup",
  "title": "Cardinality blow-up",
  "description": "Series count, memory and scrape size of the checkout app, and the trace search that replaces per-user metrics.",
  "tags": [
    "observability",
    "cardinality"
  ],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "15s",
  "time": {
    "from": "now-30m",
    "to": "now"
  },
  "editable": false,
  "panels": [
```

`uid` and `title` identify the dashboard; `tags` help search; `schemaVersion: 39` is the structure version for Grafana 11.2; `refresh: "15s"` reloads every 15 seconds; `time` is the last 30 minutes by default; `editable: false` forbids UI edits. `panels` follows.

**Panels 1 to 4 are `stat` panels**: a single big number. The first, in full:

```json
    {
      "id": 1,
      "type": "stat",
      "title": "Active series in Prometheus (head)",
      "description": "Baseline about 1.8 thousand; with a user_id label it climbs into the hundreds of thousands.",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 0,
        "y": 0,
        "w": 6,
        "h": 4
      },
      "fieldConfig": {
        "defaults": {
          "unit": "short"
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ]
        },
        "colorMode": "value"
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "prometheus_tsdb_head_series",
          "instant": true
        }
      ]
    },
```

`type: "stat"`. The `description` tells the reader what to expect: about 1.8 thousand series at the baseline, hundreds of thousands with a `user_id` label. `gridPos` places it on the 24-column grid (`x: 0, y: 0, w: 6, h: 4`: top-left, a quarter of the width, four rows). `fieldConfig.defaults.unit: "short"` formats large numbers compactly (`198 K`). `options.reduceOptions.calcs: ["lastNotNull"]` shows the last value that is not null, and `colorMode: "value"` colors the number. The single target has `expr: "prometheus_tsdb_head_series"` and `"instant": true`, which asks for one value at the current time instead of a range.

**Panel 2, Prometheus memory** (unit `bytes`, shown as KiB, MiB, GiB):

```json
    {
      "id": 2,
      "type": "stat",
      "title": "Prometheus memory",
      "description": "",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 6,
        "y": 0,
        "w": 6,
        "h": 4
      },
      "fieldConfig": {
        "defaults": {
          "unit": "bytes"
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ]
        },
        "colorMode": "value"
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "process_resident_memory_bytes{job=\"prometheus\"}",
          "instant": true
        }
      ]
    },
```

**Panel 3, samples per scrape of the app**, after relabeling (what is actually stored):

```json
    {
      "id": 3,
      "type": "stat",
      "title": "Samples per scrape of the app",
      "description": "After metric relabeling: what is actually stored.",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 12,
        "y": 0,
        "w": 6,
        "h": 4
      },
      "fieldConfig": {
        "defaults": {
          "unit": "short"
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ]
        },
        "colorMode": "value"
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "scrape_samples_post_metric_relabeling{job=\"checkout\"}",
          "instant": true
        }
      ]
    },
```

**Panel 4, duplicate samples dropped by the guard**, non-zero when the guard strips a label and series collide:

```json
    {
      "id": 4,
      "type": "stat",
      "title": "Duplicate samples dropped (guard)",
      "description": "Non-zero when the scrape guard strips a label and series collide.",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 18,
        "y": 0,
        "w": 6,
        "h": 4
      },
      "fieldConfig": {
        "defaults": {
          "unit": "short"
        },
        "overrides": []
      },
      "options": {
        "reduceOptions": {
          "calcs": [
            "lastNotNull"
          ]
        },
        "colorMode": "value"
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "increase(prometheus_target_scrapes_sample_duplicate_timestamp_total[5m])",
          "instant": true
        }
      ]
    },
```

**Panels 5 to 9 are `timeseries` graphs.** Panel 5 plots the active series over time:

```json
    {
      "id": 5,
      "type": "timeseries",
      "title": "Active series over time",
      "description": "",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 0,
        "y": 4,
        "w": 12,
        "h": 8
      },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "custom": {
            "lineWidth": 2,
            "fillOpacity": 10
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "list",
          "placement": "bottom"
        },
        "tooltip": {
          "mode": "multi"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "prometheus_tsdb_head_series",
          "legendFormat": "head series"
        }
      ]
    },
```

`options.legend` shows a list at the bottom; `tooltip.mode: "multi"` shows all series in the tooltip; `custom` sets the line width and the fill under the line.

Panel 6 plots two series for the app's scrape, before and after relabeling, so the guard's effect is visible as the gap between the lines:

```json
    {
      "id": 6,
      "type": "timeseries",
      "title": "Samples per scrape over time",
      "description": "",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 12,
        "y": 4,
        "w": 12,
        "h": 8
      },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "custom": {
            "lineWidth": 2,
            "fillOpacity": 10
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "list",
          "placement": "bottom"
        },
        "tooltip": {
          "mode": "multi"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "scrape_samples_post_metric_relabeling{job=\"checkout\"}",
          "legendFormat": "after relabeling"
        },
        {
          "refId": "B",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "scrape_samples_scraped{job=\"checkout\"}",
          "legendFormat": "as exposed"
        }
      ]
    },
```

Panel 7, requests per second by status (`sum by (status) (rate(requests_total[1m]))`, unit `reqps`):

```json
    {
      "id": 7,
      "type": "timeseries",
      "title": "Checkout requests per second by status",
      "description": "",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 0,
        "y": 12,
        "w": 12,
        "h": 8
      },
      "fieldConfig": {
        "defaults": {
          "unit": "reqps",
          "custom": {
            "lineWidth": 2,
            "fillOpacity": 10
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "list",
          "placement": "bottom"
        },
        "tooltip": {
          "mode": "multi"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "sum by (status) (rate(requests_total[1m]))",
          "legendFormat": "{{status}}"
        }
      ]
    },
```

Panel 8, the p95 of the whole route. Its description says averages hide a slow tenant: this line barely moves when one tenant's downstream call is slow.

```json
    {
      "id": 8,
      "type": "timeseries",
      "title": "Checkout p95 latency (the whole route)",
      "description": "Averages hide a slow tenant: this line barely moves when one tenant's downstream call is slow.",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 12,
        "y": 12,
        "w": 12,
        "h": 8
      },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "custom": {
            "lineWidth": 2,
            "fillOpacity": 10
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "list",
          "placement": "bottom"
        },
        "tooltip": {
          "mode": "multi"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "histogram_quantile(0.95, sum by (le) (rate(request_latency_seconds_bucket[1m])))",
          "legendFormat": "p95"
        }
      ]
    },
```

Panel 9, the cost of querying: Prometheus's own query-engine duration, the 90th percentile of the `inner_eval` slice:

```json
    {
      "id": 9,
      "type": "timeseries",
      "title": "Dashboard query cost: the lesson's sum(rate(...)) by (route)",
      "description": "",
      "datasource": {
        "type": "prometheus",
        "uid": "prometheus"
      },
      "gridPos": {
        "x": 0,
        "y": 20,
        "w": 12,
        "h": 8
      },
      "fieldConfig": {
        "defaults": {
          "unit": "s",
          "custom": {
            "lineWidth": 2,
            "fillOpacity": 10
          }
        },
        "overrides": []
      },
      "options": {
        "legend": {
          "displayMode": "list",
          "placement": "bottom"
        },
        "tooltip": {
          "mode": "multi"
        }
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "prometheus",
            "uid": "prometheus"
          },
          "expr": "prometheus_engine_query_duration_seconds{slice=\"inner_eval\",quantile=\"0.9\"}",
          "legendFormat": "inner eval p90"
        }
      ]
    },
```

**Panel 10, the table of slow traces** for the slow tenant:

```json
    {
      "id": 10,
      "type": "table",
      "title": "Slow checkout traces for one tenant (TraceQL)",
      "datasource": {
        "type": "tempo",
        "uid": "tempo"
      },
      "gridPos": {
        "x": 12,
        "y": 20,
        "w": 12,
        "h": 8
      },
      "targets": [
        {
          "refId": "A",
          "datasource": {
            "type": "tempo",
            "uid": "tempo"
          },
          "queryType": "traceql",
          "query": "{ name = \"checkout\" && span.tenant.id = \"tenant-0007\" && duration > 1s }",
          "limit": 50,
          "tableType": "traces"
        }
      ]
    }
  ],
  "templating": {
    "list": []
  },
  "annotations": {
    "list": []
  }
}
```

The data source is Tempo. `queryType: "traceql"` and the query `{ name = "checkout" && span.tenant.id = "tenant-0007" && duration > 1s }` list matching traces; `limit: 50`; `tableType: "traces"` shows one row per trace. The last lines are empty `templating` (no variables) and `annotations`.

### The Compose service

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

`GF_SECURITY_ADMIN_PASSWORD` comes from `.env` (the `:?` form stops Compose if it is empty); analytics and sign-up are off. The provisioning folder and the dashboards folder are mounted read-only, and the volume `grafana-data` holds Grafana's own database. It waits for Tempo and Prometheus to be healthy. The health check looks for the word `ok` in `/api/health`.

## Try it yourself

Open <http://127.0.0.1:23000> (user `admin`, the password from `.env`) and the dashboard "Cardinality blow-up".

```bash
curl -s -u "admin:$(grep ^GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2)" http://127.0.0.1:23000/api/datasources | python3 -c "import json,sys; print(sorted(d['uid'] for d in json.load(sys.stdin)))"
```

Expected (needs `make up`): `['prometheus', 'tempo']`.

```bash
curl -s -u "admin:$(grep ^GRAFANA_ADMIN_PASSWORD .env | cut -d= -f2)" http://127.0.0.1:23000/api/dashboards/uid/cardinality-blowup | python3 -c "import json,sys; d=json.load(sys.stdin)['dashboard']; print(d['title'], len(d['panels']))"
```

Expected: `Cardinality blow-up 10`.

```bash
.venv/bin/python -m pytest tests/observability -q
```

Expected: `13 passed`.

```bash
make health
```

Expected: five `ok` lines, the last two about Grafana querying Prometheus and Tempo.

```bash
python3 -m json.tool observability/grafana/dashboards/cardinality-blowup.json > /dev/null && echo valid
```

Expected: `valid`.

## Mistakes people make

- **Editing a provisioned dashboard in the UI** and losing the change at the next restart. Here `allowUiUpdates: false` and `editable: false` make that explicit.
- **Using a data source's name in dashboards** instead of its `uid`. Names can change; uids are stable.
- **Default passwords.** The admin password here comes from `.env` and the compose file refuses to start without it.
- **Unlinked data sources.** Without `exemplarTraceIdDestinations`, exemplar dots are not clickable.

## Check yourself

1. Does Grafana store metrics, traces or logs? *No. It queries other stores.*
2. What is provisioning? *Configuring Grafana from files at start, instead of the UI.*
3. What does `access: proxy` mean for a data source? *Grafana's server makes the queries, not the browser.*
4. What is a panel's `gridPos`? *Its position and size on the 24-column grid.*
5. Why does the dashboard refer to data sources by `uid`? *The uid is stable even if the display name changes.*

## Further reading

- Grafana 11.2 documentation: https://grafana.com/docs/grafana/v11.2/
- Provisioning: https://grafana.com/docs/grafana/v11.2/administration/provisioning/
- Dashboard JSON model: https://grafana.com/docs/grafana/v11.2/dashboards/build-dashboards/view-dashboard-json-model/
- Data source HTTP API: https://grafana.com/docs/grafana/v11.2/developers/http_api/data_source/
- Configure via environment variables: https://grafana.com/docs/grafana/v11.2/setup-grafana/configure-grafana/#override-configuration-with-environment-variables
