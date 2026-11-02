# Python threads, locks, signals and clocks (standard library)

## What it is

Four pieces of the standard library, all about doing more than one thing at a time and about stopping cleanly.

- A **thread** is a path of execution inside a process. A process can have many; they share memory. `concurrent.futures.ThreadPoolExecutor` keeps a pool of worker threads; `pool.map(function, items)` runs the function on every item using the pool and returns the results in order.
- A **lock** (`threading.Lock`) lets only one thread at a time run a protected piece of code. When threads change shared data, a lock stops two of them from changing it at once and corrupting it.
- **Thread-local storage** (`threading.local()`) gives each thread its own private set of attributes, so a value stored by one thread is invisible to the others.
- A **signal** is a small message the operating system sends to a process. `SIGTERM` means "please stop"; it is what `docker stop` sends. `SIGINT` is Ctrl-C, which Python turns into a `KeyboardInterrupt`. `SIGKILL` cannot be caught.

Clocks: `time.monotonic()` only moves forward and is right for durations; `time.time()` is the wall-clock Unix time; `time.perf_counter()` is the most precise clock for timing short operations; `time.sleep(s)` pauses the calling thread.

## Why this repository uses it

The experiment needs a lot of traffic fast: 200,000 requests from 50,000 simulated users. One request at a time would take hours, so the load generator uses 32 worker threads, each with its own HTTP session so that connections are reused. The app itself must also stop cleanly when Docker asks (SIGTERM), because the scenario restarts it many times with different settings.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/cardinality_lab/lab/load.py` | A thread pool, a thread-local session per worker and a lock around the shared counter. |
| `src/cardinality_lab/infrastructure/shutdown.py` | Turns SIGTERM into `KeyboardInterrupt`. |
| `src/cardinality_lab/interfaces/server.py` | Catches that exception and shuts the server down (see `waitress.md`). |
| `src/cardinality_lab/lab/prometheus.py`, `lab/tempo.py` | Poll with `time.monotonic()` deadlines and `time.sleep` (see `requests.md`). |

## How it works underneath

A thread pool starts its workers lazily and keeps them. `pool.map` splits the items into chunks (`chunksize=64` here, so 64 items travel to a worker together, saving overhead) and puts the chunks on a queue. Each worker takes a chunk, runs the function on each item, and returns the results. Because of the global interpreter lock only one thread runs Python code at any instant, but a thread that waits for the network lets the others run, so 32 threads keep 32 requests in flight.

`counter[status] += 1` on a shared `Counter` is a read, an add and a write: three steps that another thread could interleave with, losing an increment. Holding the lock around it makes the three steps one unit.

Python delivers signals only to the main thread, between bytecode instructions. A handler installed with `signal.signal(signal.SIGTERM, handler)` is a function Python calls then. Raising an exception from the handler interrupts whatever the main thread was doing, which is how the server loop is stopped.

## Walkthrough of this repository's use

### `infrastructure/shutdown.py`

```python
"""Turn SIGTERM into the same clean exit as Ctrl-C so in-flight work finishes before the process stops."""

from __future__ import annotations

import signal
from types import FrameType


def _raise_keyboard_interrupt(signal_number: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def install_termination_handler() -> None:
    """Make SIGTERM raise ``KeyboardInterrupt`` in the main thread, where the server loop handles it."""
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
```

`FrameType` is only a type hint: a signal handler receives the signal number and the **frame**, the interpreter's record of the code that was running. `_raise_keyboard_interrupt` ignores both and raises `KeyboardInterrupt`. `install_termination_handler` registers it for `SIGTERM`. After this call, `docker stop` behaves like Ctrl-C and the same `except KeyboardInterrupt` path in `server.py` runs.

### `lab/load.py`: simulated users and tenants

```python
"""The load generator: simulated users and tenants hitting ``GET /checkout`` with deterministic choices."""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

TENANT_COUNT = 200
```

The imports: `random` (seeded draws), `threading` (lock and thread-local), `time`, `Counter` (a dictionary that counts), the thread pool, `dataclass` and `requests`. `TENANT_COUNT = 200` is the number of tenants.

```python
def user_name(index: int) -> str:
    """The id of simulated user ``index`` (1-based): ``user-000001`` for 1, ``user-000002`` for 2."""
    return f"user-{index:06d}"


def tenant_name(index: int) -> str:
    """The id of tenant ``index`` (1-based): ``tenant-0001`` for 1, ``tenant-0002`` for 2."""
    return f"tenant-{index:04d}"
```

`user_name(12345)` returns `user-012345`: the f-string format `:06d` pads an integer with zeros to six digits. `tenant_name(7)` returns `tenant-0007`. Both names pass the identifier check in the domain.

```python
@dataclass(frozen=True, slots=True)
class LoadPlan:
    """How much traffic to send and from whom."""

    base_url: str
    users: int
    requests: int
    seed: int
    concurrency: int = 32
    tenants: int = TENANT_COUNT
```

`LoadPlan` is a frozen dataclass: the base URL, how many users, how many requests, the seed, the concurrency (default 32) and the number of tenants (default 200).

```python
@dataclass(frozen=True, slots=True)
class LoadResult:
    """What the load generator sent and what came back."""

    sent: int
    statuses: Counter[int]
    requests_per_user: Counter[str]
    requests_per_tenant: Counter[str]
    started_at: float
    finished_at: float

    @property
    def distinct_users(self) -> int:
        """How many different users appeared."""
        return len(self.requests_per_user)

    @property
    def requests_per_second(self) -> float:
        """Achieved rate."""
        return self.sent / max(self.finished_at - self.started_at, 1e-9)
```

`LoadResult` holds how many were sent, a `Counter` of HTTP statuses, a `Counter` of requests per user and per tenant, and when the run started and finished. `Counter[int]` is a type hint for a counter whose keys are integers. `distinct_users` is how many different users appeared; `requests_per_second` divides requests by elapsed time, with `max(..., 1e-9)` to avoid dividing by zero.

```python
def draw_requests(plan: LoadPlan) -> list[tuple[str, str]]:
    """The (user, tenant) pair of every request, from the plan's seeded generator."""
    rng = random.Random(plan.seed)
    return [
        (user_name(rng.randint(1, plan.users)), tenant_name(rng.randint(1, plan.tenants))) for _ in range(plan.requests)
    ]
```

`draw_requests` is a pure function: from a seeded generator it produces the list of (user, tenant) pairs for every request. `rng.randint(1, plan.users)` picks a user number between 1 and the number of users, inclusive. The same plan always gives the same list, so a run can be repeated.

```python
def run_load(plan: LoadPlan) -> LoadResult:
    """Send every drawn request with ``plan.concurrency`` workers, each with its own keep-alive session."""
    pairs = draw_requests(plan)
    local = threading.local()
    statuses: Counter[int] = Counter()
    lock = threading.Lock()

    def send(pair: tuple[str, str]) -> int:
        session = getattr(local, "session", None)
        if session is None:
            session = local.session = requests.Session()
        try:
            response = session.get(
                f"{plan.base_url}/checkout",
                headers={"X-User-Id": pair[0], "X-Tenant-Id": pair[1]},
                timeout=30,
            )
            status = response.status_code
        except requests.RequestException:
            status = 0
        with lock:
            statuses[status] += 1
        return status
```

`run_load` draws the pairs first. `local = threading.local()` is the per-thread storage; `lock = threading.Lock()` guards the counter. The inner function `send` runs in a worker thread. `getattr(local, "session", None)` looks for this thread's session; if there is none, it creates one with `requests.Session()` and stores it (`session = local.session = requests.Session()` assigns both names in one statement). The session reuses the TCP connection between requests, which matters at hundreds of requests per second. It sends `GET /checkout` with the identity in two **headers**, `X-User-Id` and `X-Tenant-Id`, and a 30-second timeout. Any `requests.RequestException` is recorded as status 0. `with lock:` makes the counter update safe.

```python
    started_at = time.time()
    with ThreadPoolExecutor(max_workers=plan.concurrency) as pool:
        list(pool.map(send, pairs, chunksize=64))
    return LoadResult(
        sent=len(pairs),
        statuses=statuses,
        requests_per_user=Counter(user for user, _ in pairs),
        requests_per_tenant=Counter(tenant for _, tenant in pairs),
        started_at=started_at,
        finished_at=time.time(),
    )
```

`list(pool.map(send, pairs, chunksize=64))` runs everything (the `list(...)` forces all results to be collected, which waits for completion). The result object counts requests per user and per tenant directly from the pairs, since every pair was sent exactly once.

## Try it yourself

```bash
.venv/bin/python -m pytest tests/unit/lab/test_load.py -q
```

Expected: `5 passed`. One test starts a throw-away HTTP server and checks every request carried both identity headers and that 10 of 100 answers were 402.

```bash
.venv/bin/python -c "
from cardinality_lab.lab.load import LoadPlan, draw_requests
pairs = draw_requests(LoadPlan('http://x', users=50000, requests=5, seed=1))
print(pairs)
print(pairs == draw_requests(LoadPlan('http://x', users=50000, requests=5, seed=1)))"
```

Expected: five (user, tenant) pairs and then `True`.

```bash
.venv/bin/python -c "
import signal, os
from cardinality_lab.infrastructure.shutdown import install_termination_handler
install_termination_handler()
try:
    os.kill(os.getpid(), signal.SIGTERM)
except KeyboardInterrupt:
    print('SIGTERM became KeyboardInterrupt')"
```

Expected: `SIGTERM became KeyboardInterrupt`.

```bash
make load USERS=500 REQUESTS=2000
```

Expected (needs `make up`): one line such as `sent 2000 requests from 480 distinct users at 900/s; statuses {200: 1940, 402: 40, 502: 20}`.

```bash
docker compose stop app && docker compose logs app | tail -3
```

Expected: the app's last lines include `shutdown requested; finishing in-flight requests` only if it logs at that level; the container exits within the 15-second grace period. Start it again with `docker compose start app`.

## Mistakes people make

- **Sharing a `requests.Session` between threads without care.** Sessions are not documented as thread-safe; this code gives each worker its own.
- **Updating a shared counter without a lock** and losing counts. The lock is held for one line only.
- **Closed-loop generators** that wait for each answer; here 32 workers keep requests in flight.
- **A signal handler that does real work.** Handlers run in the middle of other code. This one only raises.
- **Using `time.time()` for durations.** It can jump; `time.monotonic()` and `time.perf_counter()` cannot.

## Check yourself

1. Why does each worker thread have its own session? *Sessions hold connections and are not made for sharing between threads.*
2. What does the lock protect? *The shared status counter, so concurrent increments are not lost.*
3. What does `chunksize=64` do? *Sends 64 items at a time to a worker, reducing the cost of passing work around.*
4. What does SIGTERM become in this repository? *A `KeyboardInterrupt`, handled where the server loop runs.*
5. Why is the draw of users done before any request is sent? *So the plan is repeatable and the counts per user are known exactly.*

## Further reading

- `concurrent.futures`: https://docs.python.org/3.12/library/concurrent.futures.html
- `threading` (locks, `local`): https://docs.python.org/3.12/library/threading.html
- `collections.Counter`: https://docs.python.org/3.12/library/collections.html#collections.Counter
- `signal`: https://docs.python.org/3.12/library/signal.html
- `time`: https://docs.python.org/3.12/library/time.html
