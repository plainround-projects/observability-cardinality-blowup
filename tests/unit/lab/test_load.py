import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cardinality_lab.lab.load import LoadPlan, draw_requests, run_load, tenant_name, user_name


def test_names_are_zero_padded():
    assert user_name(12345) == "user-012345"
    assert tenant_name(7) == "tenant-0007"


def test_the_same_seed_draws_the_same_users_and_tenants():
    plan = LoadPlan("http://x", users=50_000, requests=2_000, seed=1)
    assert draw_requests(plan) == draw_requests(plan)
    assert draw_requests(plan) != draw_requests(LoadPlan("http://x", 50_000, 2_000, seed=2))


def test_the_draw_stays_inside_the_user_and_tenant_ranges():
    pairs = draw_requests(LoadPlan("http://x", users=50, requests=2_000, seed=3, tenants=10))
    assert {user for user, _ in pairs} <= {user_name(i) for i in range(1, 51)}
    assert {tenant for _, tenant in pairs} <= {tenant_name(i) for i in range(1, 11)}
    assert len({user for user, _ in pairs}) > 45


def test_run_load_sends_every_request_with_the_identity_headers_and_counts_statuses():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers["X-User-Id"], self.headers["X-Tenant-Id"]))
            self.send_response(402 if len(seen) % 10 == 0 else 200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        plan = LoadPlan(f"http://127.0.0.1:{server.server_address[1]}", users=20, requests=100, seed=5, concurrency=4)
        result = run_load(plan)
    finally:
        server.shutdown()
    assert result.sent == 100
    assert sorted(seen) == sorted(draw_requests(plan))
    assert result.statuses == {200: 90, 402: 10}
    assert sum(result.requests_per_user.values()) == 100
    assert result.distinct_users == len(result.requests_per_user)
    assert result.requests_per_second > 0


def test_a_dead_server_counts_as_status_zero():
    result = run_load(LoadPlan("http://127.0.0.1:9", users=2, requests=3, seed=1, concurrency=2))
    assert result.statuses == {0: 3}
