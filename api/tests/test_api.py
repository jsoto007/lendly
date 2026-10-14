from datetime import date, timedelta

TODAY = date.today()


def make_loan(admin, borrower_id, **overrides):
    payload = dict(borrower_id=borrower_id, title="Car repair", principal_cents=100_000, interest_type="simple",
                   rate_bps=1000, schedule="monthly", term_periods=4, start_date=(TODAY - timedelta(days=100)).isoformat())
    payload.update(overrides)
    r = admin.post("/api/loans", json=payload)
    assert r.status_code == 201, r.json
    return r.json["loan"]


def test_email_code_login_and_me(api):
    a = api("someone@example.com")
    r = a.get("/api/me")
    assert r.status_code == 200
    assert r.json["user"]["email"] == "someone@example.com"
    assert r.json["memberships"] == []


def test_wrong_code_rejected(client):
    client.post("/api/auth/email/request", json={"email": "x@example.com"})
    r = client.post("/api/auth/email/verify", json={"email": "x@example.com", "code": "000000"})
    assert r.status_code == 401


def test_tenant_required_and_isolation(api):
    a, b = api("a@example.com"), api("b@example.com")
    a.create_tenant("A Lending")
    b.create_tenant("B Lending")
    r = a.post("/api/borrowers", json={"name": "Alice's borrower"})
    borrower_id = r.json["borrower"]["id"]
    # B cannot see A's borrower, even with B's own tenant header
    assert b.get(f"/api/borrowers/{borrower_id}").status_code == 404
    # B cannot use A's tenant id
    b.tenant_id = a.tenant_id
    assert b.get("/api/borrowers").status_code == 403
    # No tenant header at all
    b.tenant_id = None
    assert b.get("/api/borrowers").status_code == 400


def test_full_lending_flow_with_receipts(admin):
    r = admin.post("/api/borrowers", json={"name": "Maria Lopez", "email": "Maria@Example.com", "phone": "555-0100"})
    assert r.status_code == 201
    borrower = r.json["borrower"]
    assert borrower["email"] == "maria@example.com"

    preview = admin.post("/api/loans/preview", json=dict(principal_cents=100_000, interest_type="simple", rate_bps=1000,
                                                         schedule="monthly", term_periods=4, start_date="2026-01-31"))
    assert preview.status_code == 200
    assert preview.json["state"]["total_due_cents"] == 110_000
    assert len(preview.json["installments"]) == 4

    loan = make_loan(admin, borrower["id"])
    assert loan["state"]["balance_cents"] == 110_000
    assert loan["state"]["overdue_cents"] > 0  # started 100 days ago, nothing paid

    # Record a payment → receipt R-00001 with balance snapshots
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 27_500, "method": "zelle", "note": "first"})
    assert r.status_code == 201, r.json
    p1 = r.json["payment"]
    assert p1["receipt_code"] == "R-00001"
    assert p1["balance_before_cents"] == 110_000 and p1["balance_after_cents"] == 82_500
    assert p1["lender_name"] == "Soto Lending" and p1["borrower_name"] == "Maria Lopez"

    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 500})
    assert r.json["payment"]["receipt_code"] == "R-00002"

    # Receipt endpoint
    r = admin.get(f"/api/payments/{p1['id']}/receipt")
    assert r.status_code == 200
    assert r.json["lender"]["name"] == "Soto Lending"
    assert r.json["loan"]["title"] == "Car repair"

    # Overpayment refused
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 999_999})
    assert r.status_code == 422 and r.json["error"]["code"] == "exceeds_balance"
    # Future-dated refused
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100, "paid_on": (TODAY + timedelta(days=1)).isoformat()})
    assert r.status_code == 422

    # Terms are locked once payments exist
    r = admin.patch(f"/api/loans/{loan['id']}", json={"rate_bps": 0})
    assert r.status_code == 409
    r = admin.patch(f"/api/loans/{loan['id']}", json={"title": "Car repair (Honda)"})
    assert r.status_code == 200 and r.json["loan"]["title"] == "Car repair (Honda)"

    # Void a payment → balance restored, history kept, receipt flagged
    r = admin.post(f"/api/payments/{p1['id']}/void", json={"reason": "bounced"})
    assert r.status_code == 200
    assert r.json["payment"]["voided"] is True
    assert r.json["loan"]["state"]["balance_cents"] == 109_500
    detail = admin.get(f"/api/loans/{loan['id']}").json["loan"]
    assert len(detail["payments"]) == 2
    assert any(p["voided"] for p in detail["payments"])
    r = admin.post(f"/api/payments/{p1['id']}/void", json={})
    assert r.status_code == 409

    # Pay it off → status flips to paid, and no more payments accepted
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 109_500})
    assert r.status_code == 201 and r.json["loan"]["status"] == "paid"
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 1})
    assert r.status_code == 409 and r.json["error"]["code"] == "already_paid"

    # Loans with history cannot be deleted
    assert admin.delete(f"/api/loans/{loan['id']}").status_code == 409


def test_dashboard_totals_overdue_and_upcoming(admin):
    b = admin.post("/api/borrowers", json={"name": "Dan"}).json["borrower"]
    # Overdue: started 45 days ago, monthly, nothing paid
    overdue = make_loan(admin, b["id"], start_date=(TODAY - timedelta(days=45)).isoformat())
    # Upcoming: started 10 days ago weekly → first due in 4 days
    upcoming = make_loan(admin, b["id"], title="Weekly", schedule="weekly", term_periods=4, start_date=(TODAY - timedelta(days=3)).isoformat())
    cancelled = make_loan(admin, b["id"], title="Cancelled")
    admin.patch(f"/api/loans/{cancelled['id']}", json={"status": "cancelled"})

    r = admin.get("/api/dashboard")
    assert r.status_code == 200, r.json
    d = r.json
    assert d["totals"]["lent_cents"] == 200_000
    assert d["totals"]["active_loans"] == 2 and d["totals"]["borrowers"] == 1
    assert [l["id"] for l in d["overdue"]] == [overdue["id"]]
    assert [u["loan_id"] for u in d["upcoming"]] == [upcoming["id"]]
    assert d["upcoming"][0]["amount_cents"] == 27_500
    assert len(d["monthly_collected"]) == 6

    admin.post(f"/api/loans/{overdue['id']}/payments", json={"amount_cents": 27_500})
    d = admin.get("/api/dashboard").json
    assert d["totals"]["collected_cents"] == 27_500
    assert d["overdue"] == []
    assert d["recent_payments"][0]["amount_cents"] == 27_500


def test_invite_flow_and_borrower_read_only_portal(admin, api):
    b = admin.post("/api/borrowers", json={"name": "Nina"}).json["borrower"]
    loan = make_loan(admin, b["id"])
    admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 1_000})

    r = admin.post(f"/api/borrowers/{b['id']}/invites")
    assert r.status_code == 201, r.json
    invite = r.json["invite"]
    assert len(invite["code"]) == 8 and invite["link"].endswith(invite["code"])
    # A second invite supersedes the first
    invite2 = admin.post(f"/api/borrowers/{b['id']}/invites").json["invite"]
    assert admin.get(f"/api/borrowers/{b['id']}").json["invite"]["code"] == invite2["code"]

    nina = api("nina@example.com")
    assert nina.post("/api/invites/accept", json={"code": invite["code"]}).status_code == 404  # superseded
    r = nina.post("/api/invites/accept", json={"code": invite2["code"].lower()})
    assert r.status_code == 200, r.json
    m = r.json["membership"]
    assert m["role"] == "borrower" and m["borrower_id"] == b["id"]
    # Code can't be reused by someone else
    other = api("other@example.com")
    assert other.post("/api/invites/accept", json={"code": invite2["code"]}).status_code == 404
    # Borrower is now linked; a new invite is refused
    assert admin.post(f"/api/borrowers/{b['id']}/invites").status_code == 409

    nina.tenant_id = m["tenant_id"]
    r = nina.get("/api/borrower/overview")
    assert r.status_code == 200, r.json
    assert r.json["lender"]["name"] == "Soto Lending"
    assert r.json["loans"][0]["id"] == loan["id"]
    assert r.json["payments"][0]["receipt_code"] == "R-00001"
    pid = r.json["payments"][0]["id"]
    assert nina.get(f"/api/payments/{pid}/receipt").status_code == 200
    assert nina.get(f"/api/loans/{loan['id']}").status_code == 200

    # Read-only: borrower cannot touch admin endpoints
    assert nina.get("/api/dashboard").status_code == 403
    assert nina.get("/api/borrowers").status_code == 403
    assert nina.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 1}).status_code == 403
    assert nina.patch(f"/api/loans/{loan['id']}", json={"title": "x"}).status_code == 403

    # Another borrower in the same tenant can't see Nina's loan or receipt
    b2 = admin.post("/api/borrowers", json={"name": "Omar"}).json["borrower"]
    inv = admin.post(f"/api/borrowers/{b2['id']}/invites").json["invite"]
    omar = api("omar@example.com")
    omar.tenant_id = omar.post("/api/invites/accept", json={"code": inv["code"]}).json["membership"]["tenant_id"]
    assert omar.get(f"/api/loans/{loan['id']}").status_code == 404
    assert omar.get(f"/api/payments/{pid}/receipt").status_code == 404


def test_compound_loan_end_to_end(admin):
    b = admin.post("/api/borrowers", json={"name": "Cal"}).json["borrower"]
    loan = make_loan(admin, b["id"], interest_type="compound", rate_bps=500, term_periods=3,
                     start_date=(TODAY - timedelta(days=1)).isoformat())
    assert loan["state"]["balance_cents"] == 100_000  # no period has ended yet
    assert loan["installments"][0]["status"] == "upcoming"
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 40_000})
    assert r.json["payment"]["balance_after_cents"] == 60_000
