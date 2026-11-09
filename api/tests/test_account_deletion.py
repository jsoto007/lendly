"""DELETE /api/me — App Store guideline 5.1.1(v): users must be able to delete their account."""
from sqlalchemy import text

from app.extensions import db
from tests.test_api import make_loan


def _count(table, where="", **params):
    sql = f"SELECT count(*) FROM {table}" + (f" WHERE {where}" if where else "")
    return db.session.execute(text(sql), params).scalar_one()


def _setup_lender_with_linked_borrower(api):
    lender = api("lender@example.com")
    lender.create_tenant("Soto Lending")
    r = lender.post("/api/borrowers", json={"name": "Maria Lopez", "email": "maria@example.com", "notes": "private"})
    borrower = r.json["borrower"]
    loan = make_loan(lender, borrower["id"])
    r = lender.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 27_500, "method": "zelle"})
    assert r.status_code == 201
    r = lender.post(f"/api/borrowers/{borrower['id']}/invites")
    code = r.json["invite"]["code"]
    maria = api("maria@example.com")
    r = maria.post("/api/invites/accept", json={"code": code})
    assert r.status_code == 200
    maria.tenant_id = lender.tenant_id
    return lender, maria, borrower, loan


def test_delete_requires_auth(client):
    assert client.delete("/api/me").status_code == 401


def test_lender_deletion_removes_the_workspace_and_everything_in_it(api):
    lender, maria, borrower, loan = _setup_lender_with_linked_borrower(api)
    tid = lender.tenant_id
    assert maria.get("/api/borrower/overview").status_code == 200

    r = lender.delete("/api/me")
    assert r.status_code == 204, r.data

    # The lender is gone, their session is dead, and so is every row of the workspace.
    assert lender.get("/api/me").status_code == 401
    for table in ("tenants", "borrowers", "loans", "payments", "invites", "memberships"):
        col = "id" if table == "tenants" else "tenant_id"
        assert _count(table, f"{col} = :tid", tid=tid) == 0, table
    assert _count("users", "email = 'lender@example.com'") == 0
    assert _count("otp_codes", "email = 'lender@example.com'") == 0

    # The borrower's own account survives; they just no longer belong to that workspace.
    r = maria.get("/api/me")
    assert r.status_code == 200
    assert r.json["memberships"] == []
    assert maria.get("/api/borrower/overview").status_code == 403


def test_borrower_deletion_unlinks_but_keeps_the_lenders_records(api):
    lender, maria, borrower, loan = _setup_lender_with_linked_borrower(api)

    r = maria.delete("/api/me")
    assert r.status_code == 204, r.data
    assert maria.get("/api/me").status_code == 401
    assert _count("users", "email = 'maria@example.com'") == 0

    # Lender side: nothing about the loan or its payments changed, the profile is simply unlinked.
    r = lender.get(f"/api/borrowers/{borrower['id']}")
    assert r.status_code == 200
    assert r.json["borrower"]["linked"] is False
    assert r.json["borrower"]["name"] == "Maria Lopez"
    r = lender.get(f"/api/loans/{loan['id']}")
    assert r.status_code == 200
    assert r.json["loan"]["state"]["paid_cents"] == 27_500
    assert len(r.json["loan"]["payments"]) == 1
    assert _count("payments", "loan_id = :lid", lid=loan["id"]) == 1
    assert _count("invites", "accepted_by_user_id IS NOT NULL") == 0
    # …and the lender can invite the profile again.
    assert lender.post(f"/api/borrowers/{borrower['id']}/invites").status_code == 201


def test_user_who_lends_and_borrows_is_fully_removed(api):
    # Dan lends in his own workspace and borrows in Ana's.
    ana = api("ana@example.com")
    ana.create_tenant("Ana Lending")
    r = ana.post("/api/borrowers", json={"name": "Dan"})
    dan_profile = r.json["borrower"]
    ana_loan = make_loan(ana, dan_profile["id"])
    ana.post(f"/api/loans/{ana_loan['id']}/payments", json={"amount_cents": 1_000})
    code = ana.post(f"/api/borrowers/{dan_profile['id']}/invites").json["invite"]["code"]

    dan = api("dan@example.com")
    assert dan.post("/api/invites/accept", json={"code": code}).status_code == 200
    dan.create_tenant("Dan Lending")
    r = dan.post("/api/borrowers", json={"name": "Someone"})
    dan_loan = make_loan(dan, r.json["borrower"]["id"])
    dan.post(f"/api/loans/{dan_loan['id']}/payments", json={"amount_cents": 500})
    dan_tid = dan.tenant_id

    assert dan.delete("/api/me").status_code == 204
    assert _count("tenants", "id = :t", t=dan_tid) == 0
    assert _count("payments", "tenant_id = :t", t=dan_tid) == 0
    # Ana's workspace is untouched and still consistent.
    r = ana.get(f"/api/loans/{ana_loan['id']}")
    assert r.status_code == 200 and r.json["loan"]["state"]["paid_cents"] == 1_000
    assert ana.get(f"/api/borrowers/{dan_profile['id']}").json["borrower"]["linked"] is False
    assert _count("users", "email = 'dan@example.com'") == 0
    assert _count("memberships", "user_id NOT IN (SELECT id FROM users)") == 0


def test_second_delete_with_the_old_token_is_unauthenticated(api):
    a = api("once@example.com")
    assert a.delete("/api/me").status_code == 204
    assert a.delete("/api/me").status_code == 401


def _login(client, email):
    r = client.post("/api/auth/email/request", json={"email": email})
    r = client.post("/api/auth/email/verify", json={"email": email, "code": r.json["dev_code"]})
    return r.json["token"]


def test_two_concurrent_deletes_one_wins_one_is_unauthenticated(app):
    import threading
    client = app.test_client()
    token = _login(client, "twice@example.com")
    h = {"Authorization": f"Bearer {token}"}
    client.post("/api/tenants", json={"name": "Twice"}, headers=h)
    results, barrier = [], threading.Barrier(2)

    def go():
        c = app.test_client()
        barrier.wait()
        results.append(c.delete("/api/me", headers=h).status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(results) == [204, 401], results
    assert _count("users", "email = 'twice@example.com'") == 0
    assert _count("tenants", "name = 'Twice'") == 0


def test_payment_racing_a_deletion_never_leaves_orphans(app):
    """Fire payments at a loan while its owner deletes the account. Whatever the interleaving,
    the workspace ends up fully gone with no payment rows left behind, and no request 500s."""
    import threading
    from datetime import date, timedelta
    client = app.test_client()
    token = _login(client, "racer@example.com")
    h = {"Authorization": f"Bearer {token}"}
    tenant = client.post("/api/tenants", json={"name": "Racer"}, headers=h).json["tenant"]["id"]
    h["X-Tenant-Id"] = tenant
    b = client.post("/api/borrowers", json={"name": "R"}, headers=h).json["borrower"]
    loan = client.post("/api/loans", json=dict(borrower_id=b["id"], principal_cents=100_000, interest_type="simple", rate_bps=0,
                                               schedule="monthly", term_periods=10, start_date=(date.today() - timedelta(days=1)).isoformat()),
                       headers=h).json["loan"]
    statuses = {"pay": [], "delete": []}
    barrier = threading.Barrier(4)

    def pay():
        c = app.test_client()
        barrier.wait()
        for _ in range(5):
            statuses["pay"].append(c.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100}, headers=h).status_code)

    def delete():
        c = app.test_client()
        barrier.wait()
        for _ in range(3):  # the client retries a 409 (lost race); it must never see a 500
            code = c.delete("/api/me", headers=h).status_code
            statuses["delete"].append(code)
            if code != 409:
                break

    threads = [threading.Thread(target=pay) for _ in range(3)] + [threading.Thread(target=delete)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert statuses["delete"][-1] == 204 and all(s == 409 for s in statuses["delete"][:-1]), statuses
    assert all(s in (201, 401, 403, 404, 409) for s in statuses["pay"]), statuses  # never a 500
    assert _count("tenants", "id = :t", t=tenant) == 0
    assert _count("payments", "tenant_id = :t", t=tenant) == 0
    assert _count("loans", "tenant_id = :t", t=tenant) == 0
    assert _count("payments", "loan_id NOT IN (SELECT id FROM loans)") == 0


def test_tenant_created_during_deletion_yields_409_not_500(app, api):
    """Simulates a second device creating a workspace while the account is being deleted: the
    delete must not half-apply and must not 500."""
    import threading
    from unittest.mock import patch
    from app.routes import me as me_module
    a = api("racer2@example.com")
    a.create_tenant("First")
    started, release = threading.Event(), threading.Event()
    real_delete = db.session.delete

    def slow_delete(obj):  # pause right before `db.session.delete(user)` so a POST /tenants can slip in
        started.set(); release.wait(5)
        return real_delete(obj)

    out = {}
    def do_delete():
        with patch.object(me_module.db.session, "delete", side_effect=slow_delete):
            out["delete"] = a.delete("/api/me").status_code
    t = threading.Thread(target=do_delete); t.start()
    assert started.wait(5)
    c2 = app.test_client()
    out["create"] = c2.post("/api/tenants", json={"name": "Second"}, headers={"Authorization": f"Bearer {a.token}"}).status_code
    release.set(); t.join(10)
    assert out["delete"] in (204, 409), out
    assert out["delete"] != 500
    if out["delete"] == 409:
        # nothing was removed; a retry finishes the job
        assert _count("users", "email = 'racer2@example.com'") == 1
        assert a.delete("/api/me").status_code == 204
    assert _count("users", "email = 'racer2@example.com'") == 0
    assert _count("tenants", "name IN ('First','Second')") == 0
