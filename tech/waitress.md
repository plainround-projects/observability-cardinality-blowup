# waitress

## What it is

waitress is a production-quality **WSGI server** written in pure Python. It opens a TCP port, accepts connections, reads HTTP requests, calls your WSGI application (the Flask app) in one of a pool of worker threads, and writes the response back. It runs on Windows, macOS and Linux and needs no other software. This repository uses waitress 3.0.

## Why this repository uses it

The load sends hundreds of requests per second from 32 workers, so the app needs a server with a real thread pool: 16 worker threads here. waitress also lets the code stop cleanly, so restarting the app between experiment phases never cuts a request in half.

## Where it appears

| Path | What it does with waitress |
| --- | --- |
| `src/cardinality_lab/interfaces/server.py` | `run_server`: builds the server, installs the SIGTERM handler, runs it, shuts down. |
| `src/cardinality_lab/interfaces/main.py` | Calls `run_server` as its last step. |
| `pyproject.toml` | Lists `waitress` and tells mypy to ignore its missing type information. |

## How it works underneath

waitress has one main thread that watches all connections with the operating system's `select`-style facility (it can wait for many sockets at once) and a pool of worker **threads** (here 8). When a full request has arrived, the main thread hands it to a worker, which runs the app. This means up to eight requests can be in progress at the same time, and a ninth waits in a queue.

`create_server(app, host=..., port=..., threads=8, ident=...)` builds the server object without starting it. `server.run()` starts the loop and blocks until the program is interrupted. `server.close()` closes the listening socket. Because the code calls `run()` itself, it can handle shutdown signals and run clean-up callbacks, which the one-line `serve()` helper would hide.

`ident` is the text sent in the `Server:` response header.

## Walkthrough of this repository's use

```python
"""Run a WSGI app on waitress and shut down cleanly on SIGTERM or Ctrl-C."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from flask import Flask
from waitress.server import create_server

from cardinality_lab.infrastructure.shutdown import install_termination_handler

_log = logging.getLogger(__name__)
```

`create_server` builds a waitress server object without starting it. `install_termination_handler` is the SIGTERM handler from `python-threads-and-signals.md`.

```python
def run_server(app: Flask, host: str, port: int, on_close: Sequence[Callable[[], None]] = ()) -> None:
    """Serve until SIGTERM or Ctrl-C, let in-flight requests finish, then run the ``on_close`` callbacks."""
    install_termination_handler()
    server = create_server(app, host=host, port=port, threads=16, ident="cardinality-lab")
```

`run_server(app, host, port, on_close=())` takes the Flask app, where to listen and a sequence of functions to call when the server stops. It installs the handler, then builds the server with `threads=16` (sixteen requests at the same time) and `ident="cardinality-lab"` (the `Server:` header). The socket is bound here, so a port in use fails at start-up.

```python
    _log.info("listening", extra={"host": host, "port": port})
    try:
        server.run()
```

A log line announces where it listens; `server.run()` is the blocking loop.

```python
    except KeyboardInterrupt:
        _log.info("shutdown requested; finishing in-flight requests")
    finally:
        server.close()
        for close in on_close:
            close()
        _log.info("stopped")
```

On Ctrl-C or SIGTERM (a `KeyboardInterrupt`) it logs the request to shut down. The `finally` block always runs: `server.close()` stops listening and lets workers finish their requests, then each `on_close` function runs (this app passes none) and `stopped` is logged. Compose gives the container 15 seconds (`stop_grace_period`).

## Try it yourself

```bash
docker compose exec app python -c "import waitress; print(waitress.__name__)"
```

Expected (needs `make up`): `waitress`.

```bash
docker compose stop app; docker compose ps -a app --format '{{.Status}}'; docker compose start app
```

Expected: `Exited (0)`: the process stopped by itself after SIGTERM, not killed (a kill after the grace period would show `Exited (137)`).

```bash
curl -s -D - -o /dev/null http://127.0.0.1:28082/healthz | grep -i server
```

Expected: `Server: cardinality-lab`.

```bash
docker compose logs app | grep -c listening
```

Expected: at least `0`, because the container logs at the `WARNING` level; run the app with `LOG_LEVEL=INFO` to see `listening`.

## Mistakes people make

- **Binding to `0.0.0.0` on a laptop** and exposing the service to the network. The default here is `127.0.0.1`; only the container sets `0.0.0.0`, where Docker controls the exposure.
- **Too few threads** for a service that waits on a slow dependency. Eight workers fill up if every request takes seconds.
- **Not closing** the server on exit.

## Check yourself

1. What does a WSGI server do? *Listens on a port and calls the application for each request.*
2. How many requests can this server run at once? *Eight (one per worker thread).*
3. Why call `create_server` and `run()` instead of `serve()`? *To control shutdown and clean-up.*
4. What happens to a ninth simultaneous request? *It waits in the queue until a worker is free.*
5. Why is the bind host `0.0.0.0` in the container? *So Docker can forward connections to it; the host port is bound to 127.0.0.1.*

## Further reading

- waitress 3.0 documentation: https://docs.pylonsproject.org/projects/waitress/en/stable/
- Arguments: https://docs.pylonsproject.org/projects/waitress/en/stable/arguments.html
