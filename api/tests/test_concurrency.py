"""Two admins hit the same loan at the same instant. The loan row lock must
serialize them so receipts stay unique and the second one sees the first's
balance (or is refused if the first paid it off)."""
import threading
from datetime import date, timedelta

import pytest

from app import create_app
from app.config import TestConfig


def _login(client, email):
    r = client.post("/api/auth/email/request", json={"email": email})
    r = client.post("/api/auth/email/verify", json={"email": email, "code": r.json["dev_code"]})
    return r.json["token"]


def test_concurrent_payments_get_distinct_receipts_and_consistent_balances(app):
    client = app.test_client()
    token = _login(client, "race@example.com")
    h = {"Authorization": f"Bearer {token}"}
    tenant = client.post("/api/tenants", json={"name": "Race"}, headers=h).json["tenant"]["id"]
    h["X-Tenant-Id"] = tenant
    b = client.post("/api/borrowers", json={"name": "R"}, headers=h).json["borrower"]
    loan = client.post("/api/loans", json=dict(borrower_id=b["id"], principal_cents=10_000, interest_type="simple", rate_bps=0,
                                               schedule="monthly", term_periods=2, start_date=(date.today() - timedelta(days=1)).isoformat()),
                       headers=h).json["loan"]

    results = []
    barrier = threading.Barrier(2)

    def pay(amount):
        c = app.test_client()
        barrier.wait()
        r = c.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": amount}, headers=h)
        results.append((r.status_code, r.json))

    threads = [threading.Thread(target=pay, args=(6_000,)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(s for s, _ in results)
    # First one succeeds (balance 10000 → 4000); second must be refused as exceeding the balance.
    assert statuses == [201, 422], results
    ok = next(j for s, j in results if s == 201)
    assert ok["payment"]["balance_before_cents"] == 10_000 and ok["payment"]["balance_after_cents"] == 4_000
    detail = client.get(f"/api/loans/{loan['id']}", headers=h).json["loan"]
    assert detail["state"]["balance_cents"] == 4_000
    assert len(detail["payments"]) == 1


def test_concurrent_small_payments_both_land_with_unique_receipts(app):
    client = app.test_client()
    token = _login(client, "race2@example.com")
    h = {"Authorization": f"Bearer {token}"}
    tenant = client.post("/api/tenants", json={"name": "Race2"}, headers=h).json["tenant"]["id"]
    h["X-Tenant-Id"] = tenant
    b = client.post("/api/borrowers", json={"name": "R"}, headers=h).json["borrower"]
    loan = client.post("/api/loans", json=dict(borrower_id=b["id"], principal_cents=10_000, interest_type="simple", rate_bps=0,
                                               schedule="monthly", term_periods=2, start_date=(date.today() - timedelta(days=1)).isoformat()),
                       headers=h).json["loan"]
    results = []
    barrier = threading.Barrier(4)

    def pay():
        c = app.test_client()
        barrier.wait()
        r = c.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 1_000}, headers=h)
        results.append((r.status_code, r.json))

    threads = [threading.Thread(target=pay) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [s for s, _ in results] == [201] * 4, results
    receipts = sorted(j["payment"]["receipt_number"] for _, j in results)
    assert receipts == [1, 2, 3, 4]
    befores = sorted(j["payment"]["balance_before_cents"] for _, j in results)
    assert befores == [7_000, 8_000, 9_000, 10_000]
    detail = client.get(f"/api/loans/{loan['id']}", headers=h).json["loan"]
    assert detail["state"]["balance_cents"] == 6_000
