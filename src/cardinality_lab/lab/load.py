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


def user_name(index: int) -> str:
    """The id of simulated user ``index`` (1-based): ``user-000001`` for 1, ``user-000002`` for 2."""
    return f"user-{index:06d}"


def tenant_name(index: int) -> str:
    """The id of tenant ``index`` (1-based): ``tenant-0001`` for 1, ``tenant-0002`` for 2."""
    return f"tenant-{index:04d}"


@dataclass(frozen=True, slots=True)
class LoadPlan:
    """How much traffic to send and from whom."""

    base_url: str
    users: int
    requests: int
    seed: int
    concurrency: int = 32
    tenants: int = TENANT_COUNT


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


def draw_requests(plan: LoadPlan) -> list[tuple[str, str]]:
    """The (user, tenant) pair of every request, from the plan's seeded generator."""
    rng = random.Random(plan.seed)
    return [
        (user_name(rng.randint(1, plan.users)), tenant_name(rng.randint(1, plan.tenants))) for _ in range(plan.requests)
    ]


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
