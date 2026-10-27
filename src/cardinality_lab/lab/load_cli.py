"""``cardinality-lab-load``: send simulated traffic from many users to the checkout app."""

from __future__ import annotations

import argparse
import os
import sys

from cardinality_lab.lab.load import LoadPlan, run_load


def main(argv: list[str] | None = None) -> int:
    """Run the load and print a one-line summary; exit 1 when any request failed."""
    parser = argparse.ArgumentParser(description="Send simulated traffic to the checkout app.")
    parser.add_argument("--users", type=int, default=50_000)
    parser.add_argument("--requests", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '28082')}")
    args = parser.parse_args(argv)
    result = run_load(LoadPlan(args.url, args.users, args.requests, args.seed, args.concurrency))
    print(
        f"sent {result.sent} requests from {result.distinct_users} distinct users "
        f"at {result.requests_per_second:.0f}/s; statuses {dict(sorted(result.statuses.items()))}"
    )
    return 1 if result.statuses.get(0) or any(s >= 500 and s != 502 for s in result.statuses) else 0


if __name__ == "__main__":
    sys.exit(main())
