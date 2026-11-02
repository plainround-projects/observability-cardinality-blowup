# HTTP (what the app, Prometheus and the lab tools say to each other)

## What it is

HTTP is the protocol (the agreed rules) that programs use to talk over a network. A **client** sends a **request**; a **server** sends back a **response**. A request has a **method** (`GET` reads, `POST` creates or sends data), a **path** (`/order/3`), **headers** (extra information as `Name: value` lines) and sometimes a **body**. A response has a **status code**, headers and a body. This repository's services, the monitoring stores, Grafana and the Collector all speak HTTP.

## Why this repository uses it

Every arrow in the lab is an HTTP call: the load generator calls the app with the user's identity in headers, Prometheus scrapes the app's metrics page, the app sends spans to the Collector, the Collector sends them to Tempo, Grafana queries Prometheus and Tempo, and the lab client asks Prometheus and Tempo questions. The lesson's metric (`requests_total{status="402"}`) is literally a count of HTTP status codes.

## Where it appears

| Where | The HTTP involved |
| --- | --- |
| `interfaces/http_app.py` | The route `GET /checkout`, the identity headers, the statuses, the `X-Trace-Id` response header. |
| `lab/load.py` | Sends the load with `X-User-Id` and `X-Tenant-Id`. |
| `lab/prometheus.py`, `lab/tempo.py` | Calls to the stores' APIs with timeouts and one retry. |
| `observability/prometheus/prometheus.yml` | A scrape is `GET http://app:9100/metrics` every 60 s. |
| `docker-compose.yml` | Published ports and HTTP health checks. |

## How it works underneath

The client opens a **TCP connection** to the server's address and **port** (a number that picks one program on that machine, such as 8080). It writes the request as text lines. The server reads them, does the work and writes the response. Status codes are grouped by first digit: `2xx` success (`200 OK`), `3xx` redirect, `4xx` the client made a mistake (`400 Bad Request`, `404 Not Found`), `5xx` the server failed (`500`, `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout`).

A **timeout** is how long the client waits before giving up. A **connection timeout** applies to opening the connection; a **read timeout** applies to waiting for the response bytes. A **retry** sends the same request again after a failure; it is only safe for requests that change nothing (`GET` is idempotent).

The address `127.0.0.1` (also `localhost`) is the loopback address: it always means "this same machine". `0.0.0.0` as a *listen* address means "all network interfaces of this machine".

A **health endpoint** (here `/healthz`) is a path that answers 200 when the service can do its job; orchestrators and Docker call it repeatedly.

A **header** can carry the trace identity between services. `traceparent` is the W3C standard header that OpenTelemetry uses to pass the trace id and the parent span id from the caller to the callee.

## Walkthrough of this repository's use

**One request.** The load generator sends

```text
GET /checkout HTTP/1.1
Host: 127.0.0.1:28082
X-User-Id: user-000042
X-Tenant-Id: tenant-0007
```

The header names starting `X-` are the project's own, not part of the standard. The app turns the headers into a `UserId` and a `TenantId` (400 if invalid):

```python
    @app.get("/checkout")
    def get_checkout() -> tuple[Response, int]:
        outcome = checkout.execute(
            CheckoutRequest(
                user=UserId(request.headers.get("X-User-Id", "")),
                tenant=TenantId(request.headers.get("X-Tenant-Id", "")),
            )
        )
        return jsonify({"outcome": outcome.name.lower()}), outcome.status
```

The answer is a status that tells the outcome: `200 OK` approved, `402 Payment Required` declined, `502 Bad Gateway` the payment gateway failed. The load command treats 502 as expected and any other 5xx as a failure:

```python
    return 1 if result.statuses.get(0) or any(s >= 500 and s != 502 for s in result.statuses) else 0
```

**The status becomes a metric label.** The status is one of the three bounded labels of the metric (`status="200"`, `"402"`, `"502"`); it is bounded because the app only ever produces those three.

**A scrape.** Prometheus sends `GET /metrics` to `app:9100`. The answer is plain text, one line per series. With the mistake on, the answer is tens of megabytes, which is why the job's scrape interval is 60 s and its timeout 55 s (see `prometheus.md`).

**Timeouts and one retry.** The Prometheus client waits up to 300 seconds for an answer and retries a timeout once:

```python
    def _get(self, path: str, params: Mapping[str, str] | None = None, timeout: float = 300.0) -> dict[str, Any]:
        """GET a Prometheus API path; a blown-up Prometheus can take minutes to answer, so one timeout is retried."""
        for attempt in range(2):
            try:
                response = self._session.get(f"{self._base}{path}", params=params, timeout=timeout)
                break
            except requests.Timeout as error:
                if attempt == 1:
                    raise PrometheusError(f"GET {path} timed out twice: {error}") from error
            except requests.RequestException as error:
                raise PrometheusError(f"GET {path} failed: {error}") from error
        if response.status_code != 200:
            raise PrometheusError(f"Prometheus answered {response.status_code} for {path}: {response.text[:200]}")
        body: dict[str, Any] = response.json()
        if body.get("status") != "success":
            raise PrometheusError(f"Prometheus query failed: {body}")
        return body
```

(This is `GET`, which is safe to repeat.)

## Try it yourself

```bash
curl -s -i -H "X-User-Id: user-000042" -H "X-Tenant-Id: tenant-0007" http://127.0.0.1:28082/checkout | head -12
```

Expected (needs `make up`): `HTTP/1.1 200 OK` (or 402 or 502), headers including `Content-Type: application/json`, `X-Trace-Id` and `Server: cardinality-lab`, then the body.

```bash
for i in $(seq 1 100); do curl -s -o /dev/null -w "%{http_code}\n" -H "X-User-Id: user-$i" -H "X-Tenant-Id: tenant-0001" http://127.0.0.1:28082/checkout; done | sort | uniq -c
```

Expected: about 97 answers with 200, a few 402 and an occasional 502 (the policy: 2 percent declined, 1 percent errors).

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:28082/checkout
```

Expected: `400` (no identity headers).

```bash
docker compose exec prometheus wget -q -O - http://app:9100/metrics | head -5
```

Expected: the first lines of the metrics page (`# HELP` and `# TYPE` comments, then series).

```bash
curl -s -o /dev/null -w "%{http_code} %{size_download} bytes\n" --max-time 5 http://127.0.0.1:29090/-/healthy
```

Expected: `200` and a few bytes.

## Mistakes people make

- **No timeout.** A call without a timeout can wait forever. Every client call here sets one.
- **Retrying non-idempotent calls.** Retrying a payment could charge twice.
- **Using `0.0.0.0` as a destination.** It is only meaningful as a listen address.
- **Confusing 502, 503 and 504.** 502: a gateway got a bad answer; 503: not ready or overloaded; 504: the upstream did not answer in time.

## Check yourself

1. What are the parts of an HTTP request? *Method, path, headers, optional body.*
2. What does a 404 mean? *The thing asked for was not found.*
3. Which statuses count as server failures? *The 5xx family.*
4. What does listening on `127.0.0.1` allow? *Only connections from the same machine.*
5. Why is `GET` safe to retry? *It does not change anything on the server.*

## Further reading

- MDN, HTTP overview: https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview
- HTTP semantics (RFC 9110): https://www.rfc-editor.org/rfc/rfc9110
- W3C Trace Context (the `traceparent` header): https://www.w3.org/TR/trace-context/
