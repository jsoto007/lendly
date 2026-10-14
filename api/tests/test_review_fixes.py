"""Regressions for the money-safety review findings (2026-10-14)."""
import threading
from datetime import date, timedelta

from app.services.schedule import LoanTerms, PaymentLike, compute_state, raw_balance

from tests.test_api import make_loan

TODAY = date.today()


def compound(**kw):
    base = dict(principal_cents=100_000, interest_type="compound", rate_bps=1000, fixed_fee_cents=0,
                fixed_fee_per_period=False, schedule="monthly", term_periods=1, start_date=date(2026, 1, 31))
    base.update(kw)
    return LoanTerms(**base)


# --- HIGH (math): payment ON the due date is applied after that period's interest -----------
def test_payment_on_due_date_does_not_erase_that_periods_interest():
    t = compound()  # due 2026-02-28, 10%
    on_due = compute_state(t, [PaymentLike(100_000, date(2026, 2, 28))], date(2026, 2, 28))
    day_after = compute_state(t, [PaymentLike(100_000, date(2026, 3, 1))], date(2026, 3, 1))
    day_before = compute_state(t, [PaymentLike(100_000, date(2026, 2, 27))], date(2026, 2, 28))
    assert on_due.balance_cents == 10_000
    assert day_after.balance_cents == 10_000
    assert day_before.balance_cents == 0 and day_before.is_paid_off


def test_amortized_schedule_paid_on_due_dates_retires_exactly_to_zero():
    from app.services.schedule import build_schedule
    t = compound(rate_bps=200, term_periods=4)
    s = build_schedule(t)
    pays = [PaymentLike(i.amount_cents, i.due_date) for i in s]
    assert raw_balance(t, pays, s[-1].due_date) == 0  # exact, not clamped


# --- Due-day semantics: the borrower gets the whole due day ---------------------------------
def test_installment_due_today_is_next_not_overdue():
    t = LoanTerms(principal_cents=100_000, interest_type="simple", rate_bps=1000, fixed_fee_cents=0,
                  fixed_fee_per_period=False, schedule="monthly", term_periods=4, start_date=date(2026, 1, 31))
    st = compute_state(t, [], date(2026, 2, 28))
    assert st.overdue_cents == 0 and st.next_due_date == date(2026, 2, 28)
    st = compute_state(t, [], date(2026, 3, 1))
    assert st.overdue_cents == 27_500 and st.days_overdue == 1


# --- progress reflects late interest ---------------------------------------------------------
def test_progress_not_complete_while_late_interest_remains():
    t = compound()
    st = compute_state(t, [PaymentLike(110_000, date(2026, 4, 30))], date(2026, 4, 30))
    assert not st.is_paid_off and st.balance_cents > 0
    assert st.progress < 1.0


# --- HIGH (authz/concurrency): PATCH terms vs concurrent payment -----------------------------
def test_patch_terms_races_with_payment_and_loses(app, admin):
    b = admin.post("/api/borrowers", json={"name": "Race"}).json["borrower"]
    loan = make_loan(admin, b["id"], start_date=(TODAY - timedelta(days=1)).isoformat())
    results = {}
    barrier = threading.Barrier(2)
    h = admin.headers()

    def patch():
        c = app.test_client()
        barrier.wait()
        results["patch"] = c.patch(f"/api/loans/{loan['id']}", json={"rate_bps": 0}, headers=h)

    def pay():
        c = app.test_client()
        barrier.wait()
        results["pay"] = c.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 50_000}, headers=h)

    ts = [threading.Thread(target=patch), threading.Thread(target=pay)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert results["pay"].status_code == 201
    # Either the patch ran first (then terms changed and the payment used the new terms) or it
    # ran second and was refused. It must never silently rewrite terms under a live payment.
    detail = admin.get(f"/api/loans/{loan['id']}").json["loan"]
    if results["patch"].status_code == 200:
        assert detail["rate_bps"] == 0 and detail["state"]["total_due_cents"] == 100_000
        assert detail["payments"][0]["balance_before_cents"] == 100_000
    else:
        assert results["patch"].status_code == 409
        assert detail["rate_bps"] == 1000


# --- back-dated compound overpayment ---------------------------------------------------------
def test_backdated_compound_payment_cannot_exceed_balance_on_that_date(admin):
    b = admin.post("/api/borrowers", json={"name": "C"}).json["borrower"]
    start = TODAY - timedelta(days=8)
    loan = make_loan(admin, b["id"], interest_type="compound", rate_bps=500, schedule="weekly", term_periods=2,
                     start_date=start.isoformat())
    assert loan["state"]["balance_cents"] == 105_000  # one week accrued
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 105_000, "paid_on": start.isoformat()})
    assert r.status_code == 422 and r.json["error"]["code"] == "exceeds_balance"
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100_000, "paid_on": start.isoformat()})
    assert r.status_code == 201
    assert r.json["payment"]["balance_before_cents"] == 100_000 and r.json["payment"]["balance_after_cents"] == 0
    assert r.json["loan"]["status"] == "paid"


def test_backdated_payment_that_overpays_after_replay_is_refused(admin):
    b = admin.post("/api/borrowers", json={"name": "C2"}).json["borrower"]
    start = TODAY - timedelta(days=15)
    loan = make_loan(admin, b["id"], interest_type="compound", rate_bps=1000, schedule="weekly", term_periods=1,
                     start_date=start.isoformat())
    # week 1 end: 110_000; pay 100_000 the day after → 10_000; week 2 end: 11_000 owed today
    admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100_000, "paid_on": (start + timedelta(days=8)).isoformat()})
    assert admin.get(f"/api/loans/{loan['id']}").json["loan"]["state"]["balance_cents"] == 11_000
    # 11_000 fits both today's balance and the balance on day 2, but replaying it overpays.
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 11_000, "paid_on": (start + timedelta(days=2)).isoformat()})
    assert r.status_code == 422
    assert admin.get(f"/api/loans/{loan['id']}").json["loan"]["state"]["balance_cents"] == 11_000


# --- cancel guard, idempotency, notes, re-link, caps, archived, limit --------------------------
def test_cannot_cancel_loan_with_live_payments(admin):
    b = admin.post("/api/borrowers", json={"name": "D"}).json["borrower"]
    loan = make_loan(admin, b["id"])
    p = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 1_000}).json["payment"]
    assert admin.patch(f"/api/loans/{loan['id']}", json={"status": "cancelled"}).status_code == 409
    admin.post(f"/api/payments/{p['id']}/void", json={})
    r = admin.patch(f"/api/loans/{loan['id']}", json={"status": "cancelled"})
    assert r.status_code == 200 and r.json["loan"]["status"] == "cancelled"
    assert r.json["loan"]["state"]["overdue_cents"] == 0 and r.json["loan"]["state"]["next_due_date"] is None
    assert {i["status"] for i in r.json["loan"]["installments"]} == {"cancelled"}


def test_idempotent_payment_retry_records_once(admin):
    b = admin.post("/api/borrowers", json={"name": "E"}).json["borrower"]
    loan = make_loan(admin, b["id"])
    body = {"amount_cents": 27_500, "idempotency_key": "ios-abc-123"}
    r1 = admin.post(f"/api/loans/{loan['id']}/payments", json=body)
    r2 = admin.post(f"/api/loans/{loan['id']}/payments", json=body)
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json["payment"]["id"] == r2.json["payment"]["id"]
    detail = admin.get(f"/api/loans/{loan['id']}").json["loan"]
    assert len(detail["payments"]) == 1 and detail["state"]["balance_cents"] == 82_500


def test_private_notes_hidden_from_borrower(admin, api):
    b = admin.post("/api/borrowers", json={"name": "F", "notes": "PRIVATE borrower note"}).json["borrower"]
    loan = make_loan(admin, b["id"], notes="PRIVATE loan note")
    code = admin.post(f"/api/borrowers/{b['id']}/invites").json["invite"]["code"]
    u = api("f@example.com")
    u.tenant_id = u.post("/api/invites/accept", json={"code": code}).json["membership"]["tenant_id"]
    overview = u.get("/api/borrower/overview").json
    assert overview["borrower"]["notes"] is None
    assert overview["loans"][0]["notes"] is None
    assert u.get(f"/api/loans/{loan['id']}").json["loan"]["notes"] is None
    # admin still sees them
    assert admin.get(f"/api/loans/{loan['id']}").json["loan"]["notes"] == "PRIVATE loan note"


def test_user_cannot_relink_to_second_borrower_profile(admin, api):
    a = admin.post("/api/borrowers", json={"name": "A"}).json["borrower"]
    b = admin.post("/api/borrowers", json={"name": "B"}).json["borrower"]
    code_a = admin.post(f"/api/borrowers/{a['id']}/invites").json["invite"]["code"]
    code_b = admin.post(f"/api/borrowers/{b['id']}/invites").json["invite"]["code"]
    u = api("ab@example.com")
    assert u.post("/api/invites/accept", json={"code": code_a}).status_code == 200
    r = u.post("/api/invites/accept", json={"code": code_b})
    assert r.status_code == 409 and r.json["error"]["code"] == "already_linked"
    assert admin.get(f"/api/borrowers/{b['id']}").json["borrower"]["linked"] is False


def test_oversized_amounts_and_rates_are_422_not_500(admin):
    b = admin.post("/api/borrowers", json={"name": "G"}).json["borrower"]
    base = dict(borrower_id=b["id"], interest_type="simple", rate_bps=0, schedule="monthly", term_periods=1)
    # Above the int32 limit but under the $1B cap: fine now that cents columns are BigInteger.
    assert admin.post("/api/loans", json={**base, "principal_cents": 2_147_483_648}).status_code == 201
    assert admin.post("/api/loans", json={**base, "principal_cents": 200_000_000_000}).status_code == 422
    assert admin.post("/api/loans", json={**base, "principal_cents": 1_000, "rate_bps": 20_000}).status_code == 422
    loan = make_loan(admin, b["id"])
    assert admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 200_000_000_000}).status_code == 422
    assert admin.get("/api/payments?limit=abc").status_code == 422
    assert admin.get("/api/payments?limit=-1").status_code == 200


def test_archived_borrower_cannot_get_loans_or_invites(admin):
    b = admin.post("/api/borrowers", json={"name": "H"}).json["borrower"]
    assert admin.patch(f"/api/borrowers/{b['id']}", json={"archived": "false"}).status_code == 422
    assert admin.patch(f"/api/borrowers/{b['id']}", json={"archived": True}).json["borrower"]["archived"] is True
    r = admin.post("/api/loans", json=dict(borrower_id=b["id"], principal_cents=1_000, interest_type="simple",
                                           rate_bps=0, schedule="monthly", term_periods=1))
    assert r.status_code == 409
    assert admin.post(f"/api/borrowers/{b['id']}/invites").status_code == 409


def test_null_term_keeps_existing_value_and_voided_payment_is_frozen(admin):
    b = admin.post("/api/borrowers", json={"name": "I"}).json["borrower"]
    start = (TODAY - timedelta(days=100)).isoformat()
    loan = make_loan(admin, b["id"], start_date=start)
    r = admin.patch(f"/api/loans/{loan['id']}", json={"start_date": None, "rate_bps": None, "title": "Kept"})
    assert r.status_code == 200
    assert r.json["loan"]["start_date"] == start and r.json["loan"]["rate_bps"] == 1000
    p = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 500}).json["payment"]
    admin.post(f"/api/payments/{p['id']}/void", json={"reason": "oops"})
    assert admin.patch(f"/api/payments/{p['id']}", json={"note": "edited"}).status_code == 409


def test_concurrent_double_void_only_one_succeeds(app, admin):
    b = admin.post("/api/borrowers", json={"name": "J"}).json["borrower"]
    loan = make_loan(admin, b["id"])
    p = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 500}).json["payment"]
    results = []
    barrier = threading.Barrier(2)
    h = admin.headers()

    def void(reason):
        c = app.test_client()
        barrier.wait()
        results.append(c.post(f"/api/payments/{p['id']}/void", json={"reason": reason}, headers=h).status_code)

    ts = [threading.Thread(target=void, args=(r,)) for r in ("first", "second")]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sorted(results) == [200, 409]


def test_local_date_header_drives_today(admin):
    b = admin.post("/api/borrowers", json={"name": "K"}).json["borrower"]
    loan = make_loan(admin, b["id"], start_date=TODAY.isoformat())
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    # Server thinks it's today; the client says its local date is tomorrow (e.g. 9pm New York vs UTC+1 day).
    r = admin.client.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100, "paid_on": tomorrow},
                          headers={**admin.headers(), "X-Local-Date": tomorrow})
    assert r.status_code == 201
    # A wildly wrong clock is ignored.
    far = (TODAY + timedelta(days=30)).isoformat()
    r = admin.client.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 100, "paid_on": far},
                          headers={**admin.headers(), "X-Local-Date": far})
    assert r.status_code == 422


# --- adversarial pass round 2 -----------------------------------------------------------------
def test_far_future_start_date_is_422_and_never_persists(admin):
    b = admin.post("/api/borrowers", json={"name": "FF"}).json["borrower"]
    body = dict(borrower_id=b["id"], principal_cents=1_000, interest_type="simple", rate_bps=0,
                schedule="monthly", term_periods=1, start_date="9999-12-31")
    assert admin.post("/api/loans", json=body).status_code == 422
    assert admin.post("/api/loans/preview", json=body).status_code == 422
    assert admin.get("/api/loans").status_code == 200
    assert admin.get("/api/dashboard").status_code == 200
    loan = make_loan(admin, b["id"])
    assert admin.patch(f"/api/loans/{loan['id']}", json={"start_date": "2150-01-01"}).status_code == 422
    assert admin.get(f"/api/loans/{loan['id']}").json["loan"]["start_date"] == loan["start_date"]


def test_idempotency_key_is_scoped_to_loan_and_amount(admin):
    b = admin.post("/api/borrowers", json={"name": "IK"}).json["borrower"]
    a = make_loan(admin, b["id"], title="A")
    bb = make_loan(admin, b["id"], title="B")
    r = admin.post(f"/api/loans/{a['id']}/payments", json={"amount_cents": 1_000, "idempotency_key": "k1"})
    assert r.status_code == 201
    # same key on another loan → conflict, nothing recorded on B
    r = admin.post(f"/api/loans/{bb['id']}/payments", json={"amount_cents": 1_000, "idempotency_key": "k1"})
    assert r.status_code == 409 and r.json["error"]["code"] == "idempotency_conflict"
    assert admin.get(f"/api/loans/{bb['id']}").json["loan"]["payments"] == []
    # same key, different amount → conflict
    r = admin.post(f"/api/loans/{a['id']}/payments", json={"amount_cents": 2_000, "idempotency_key": "k1"})
    assert r.status_code == 409
    # void frees the key: a re-record with the same key is a NEW payment
    pid = admin.get(f"/api/loans/{a['id']}").json["loan"]["payments"][0]["id"]
    admin.post(f"/api/payments/{pid}/void", json={})
    r = admin.post(f"/api/loans/{a['id']}/payments", json={"amount_cents": 1_000, "idempotency_key": "k1"})
    assert r.status_code == 201 and r.json["payment"]["voided"] is False
    assert admin.get(f"/api/loans/{a['id']}").json["loan"]["state"]["balance_cents"] == 109_000


def test_concurrent_same_key_different_loans_never_500(app, admin):
    b = admin.post("/api/borrowers", json={"name": "IK2"}).json["borrower"]
    loans = [make_loan(admin, b["id"], title=t) for t in ("X", "Y")]
    results = []
    barrier = threading.Barrier(2)
    h = admin.headers()

    def pay(loan_id):
        c = app.test_client()
        barrier.wait()
        results.append(c.post(f"/api/loans/{loan_id}/payments", json={"amount_cents": 500, "idempotency_key": "race"}, headers=h).status_code)

    ts = [threading.Thread(target=pay, args=(l["id"],)) for l in loans]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sorted(results) == [201, 409], results


def test_backdated_receipt_snapshots_use_chronological_balance(admin):
    b = admin.post("/api/borrowers", json={"name": "BD"}).json["borrower"]
    start = TODAY - timedelta(days=15)
    loan = make_loan(admin, b["id"], interest_type="compound", rate_bps=1000, schedule="weekly", term_periods=1,
                     start_date=start.isoformat())
    # Pay 50_000 on day 7 (the due date, applied after the 10% charge): 110_000 → 60_000; today 66_000.
    admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 50_000, "paid_on": (start + timedelta(days=7)).isoformat()})
    assert admin.get(f"/api/loans/{loan['id']}").json["loan"]["state"]["balance_cents"] == 66_000
    # Back-date 40_000 to day 2: balance on that date was 100_000, so the receipt must say 100_000 → 60_000,
    # and the request must be accepted (replayed raw balance stays positive).
    r = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 40_000, "paid_on": (start + timedelta(days=2)).isoformat()})
    assert r.status_code == 201, r.json
    assert r.json["payment"]["balance_before_cents"] == 100_000 and r.json["payment"]["balance_after_cents"] == 60_000
    # 52_000 back-dated would also be fine chronologically and leaves the loan positive after replay.
    loan2 = make_loan(admin, b["id"], interest_type="compound", rate_bps=1000, schedule="weekly", term_periods=1,
                      start_date=start.isoformat(), title="L2")
    admin.post(f"/api/loans/{loan2['id']}/payments", json={"amount_cents": 50_000, "paid_on": (start + timedelta(days=7)).isoformat()})
    r = admin.post(f"/api/loans/{loan2['id']}/payments", json={"amount_cents": 52_000, "paid_on": (start + timedelta(days=2)).isoformat()})
    assert r.status_code == 201, r.json
    # but 60_000 would overpay once replayed → refused
    loan3 = make_loan(admin, b["id"], interest_type="compound", rate_bps=1000, schedule="weekly", term_periods=1,
                      start_date=start.isoformat(), title="L3")
    admin.post(f"/api/loans/{loan3['id']}/payments", json={"amount_cents": 50_000, "paid_on": (start + timedelta(days=7)).isoformat()})
    r = admin.post(f"/api/loans/{loan3['id']}/payments", json={"amount_cents": 60_000, "paid_on": (start + timedelta(days=2)).isoformat()})
    assert r.status_code == 422


def test_void_reason_hidden_from_borrower(admin, api):
    b = admin.post("/api/borrowers", json={"name": "VR"}).json["borrower"]
    loan = make_loan(admin, b["id"])
    p = admin.post(f"/api/loans/{loan['id']}/payments", json={"amount_cents": 500}).json["payment"]
    admin.post(f"/api/payments/{p['id']}/void", json={"reason": "SECRET bounced check"})
    code = admin.post(f"/api/borrowers/{b['id']}/invites").json["invite"]["code"]
    u = api("vr@example.com")
    u.tenant_id = u.post("/api/invites/accept", json={"code": code}).json["membership"]["tenant_id"]
    for body in (u.get(f"/api/loans/{loan['id']}").json, u.get(f"/api/payments/{p['id']}/receipt").json, u.get("/api/borrower/overview").json):
        assert "SECRET" not in str(body)
    assert admin.get(f"/api/payments/{p['id']}/receipt").json["payment"]["void_reason"] == "SECRET bounced check"


def test_concurrent_invite_accepts_are_409_not_500(app, admin, api):
    a = admin.post("/api/borrowers", json={"name": "CA"}).json["borrower"]
    bb = admin.post("/api/borrowers", json={"name": "CB"}).json["borrower"]
    codes = [admin.post(f"/api/borrowers/{x['id']}/invites").json["invite"]["code"] for x in (a, bb)]
    u = api("ca@example.com")
    results = []
    barrier = threading.Barrier(2)
    h = u.headers()

    def accept(code):
        c = app.test_client()
        barrier.wait()
        results.append(c.post("/api/invites/accept", json={"code": code}, headers=h).status_code)

    ts = [threading.Thread(target=accept, args=(c,)) for c in codes]
    for t in ts: t.start()
    for t in ts: t.join()
    assert sorted(results) == [200, 409], results
