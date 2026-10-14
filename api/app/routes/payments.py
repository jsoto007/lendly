from datetime import date

from flask import Blueprint, g, request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..auth import api_error, require_tenant
from ..extensions import db
from ..models import PAYMENT_METHODS, Loan, Payment, Tenant
from ..serializers import live_payments, loan_json, payment_json, state_of, terms_of, today
from ..services.schedule import PaymentLike, compute_state, raw_balance
from ._helpers import (MAX_CENTS, BadInput, body, handle_bad_input, parse_uuid, query_int, req_choice,
                       req_date, req_int, req_str)

bp = Blueprint("payments", __name__)
handle_bad_input(bp)


def _locked_loan(loan_id) -> Loan | None:
    loan = db.session.execute(
        db.select(Loan).where(Loan.id == parse_uuid(loan_id), Loan.tenant_id == g.tenant.id).with_for_update()
    ).scalar_one_or_none()
    return loan


def _next_receipt_number(tenant_id) -> int:
    # Atomic per-tenant counter: the UPDATE serializes concurrent payments.
    return db.session.execute(
        text("UPDATE tenants SET receipt_seq = receipt_seq + 1 WHERE id = :tid RETURNING receipt_seq"),
        {"tid": tenant_id},
    ).scalar_one()


def _find_idempotent(key: str) -> Payment | None:
    return db.session.execute(
        db.select(Payment).where(Payment.tenant_id == g.tenant.id, Payment.idempotency_key == key,
                                 Payment.voided_at.is_(None))
    ).scalar_one_or_none()


def _idempotency_race(idem, loan, amount, paid_on):
    """Two retries with the same key raced; the first one won. Answer like a normal retry."""
    db.session.rollback()
    dup = _find_idempotent(idem) if idem else None
    if dup is not None and dup.loan_id == loan.id and dup.amount_cents == amount and dup.paid_on == paid_on:
        return {"payment": payment_json(dup, dup.loan, g.tenant), "loan": loan_json(dup.loan, detail=True)}, 200
    return api_error(409, "idempotency_conflict", "This request key was already used for a different payment.")


def _receipt_payload(p: Payment) -> dict:
    loan = p.loan
    tenant = db.session.get(Tenant, p.tenant_id)
    return {
        "payment": payment_json(p, loan, tenant),
        "loan": {
            "id": str(loan.id),
            "title": loan.title,
            "principal_cents": loan.principal_cents,
            "interest_type": loan.interest_type,
            "rate_bps": loan.rate_bps,
            "fixed_fee_cents": loan.fixed_fee_cents,
            "fixed_fee_per_period": loan.fixed_fee_per_period,
            "schedule": loan.schedule,
            "term_periods": loan.term_periods,
            "start_date": loan.start_date.isoformat(),
            "status": loan.status,
        },
        "borrower": {"id": str(loan.borrower.id), "name": loan.borrower.name, "email": loan.borrower.email},
        "lender": {"id": str(tenant.id), "name": tenant.name},
    }


@bp.post("/loans/<loan_id>/payments")
@require_tenant("admin")
def record_payment(loan_id):
    loan = _locked_loan(loan_id)
    if loan is None:
        return api_error(404, "not_found", "Loan not found.")
    if loan.status == "cancelled":
        return api_error(409, "loan_cancelled", "This loan is cancelled. Reactivate it to record payments.")
    data = body()
    amount = req_int(data, "amount_cents", minimum=1, maximum=MAX_CENTS)
    now = today()
    paid_on = req_date(data, "paid_on", required=False, default=now)
    method = req_choice(data, "method", PAYMENT_METHODS, required=False, default="cash")
    note = req_str(data, "note", max_len=500, required=False)
    idem = req_str(data, "idempotency_key", max_len=64, required=False)
    if paid_on > now:
        raise BadInput("Payment date can't be in the future.")
    if paid_on < loan.start_date:
        raise BadInput("Payment date is before the loan started.")

    if idem:
        # A retried request (same key) returns the payment it already created instead of a duplicate.
        dup = _find_idempotent(idem)
        if dup is not None:
            if dup.loan_id != loan.id or dup.amount_cents != amount or dup.paid_on != paid_on:
                return api_error(409, "idempotency_conflict", "This request key was already used for a different payment.")
            return {"payment": payment_json(dup, dup.loan, g.tenant), "loan": loan_json(dup.loan, detail=True)}, 200

    before_today = state_of(loan, now)
    if before_today.is_paid_off:
        return api_error(409, "already_paid", "This loan is already paid off.")
    # For compound loans a back-dated payment must fit the balance that existed on that date,
    # otherwise the receipt would show more collected than was ever owed. "On that date" means
    # the chronological history up to paid_on — later-dated payments don't exist yet.
    terms = terms_of(loan)
    history = [PaymentLike(p.amount_cents, p.paid_on) for p in live_payments(loan) if p.paid_on <= paid_on]
    before = compute_state(terms, history, paid_on)
    limit = min(before.balance_cents, before_today.balance_cents)
    if amount > limit:
        return api_error(422, "exceeds_balance", f"Amount exceeds the balance owed on that date ({limit / 100:.2f}).")

    payment = Payment(
        tenant_id=g.tenant.id,
        loan_id=loan.id,
        amount_cents=amount,
        paid_on=paid_on,
        method=method,
        note=note,
        receipt_number=_next_receipt_number(g.tenant.id),
        balance_before_cents=before.balance_cents,
        balance_after_cents=before.balance_cents,  # placeholder until recomputed below
        idempotency_key=idem,
        created_by_user_id=g.user.id,
    )
    db.session.add(payment)
    loan.payments.append(payment)
    try:
        db.session.flush()
    except IntegrityError:
        return _idempotency_race(idem, loan, amount, paid_on)
    # A back-dated payment changes how much interest accrued afterwards; make sure the loan
    # never ends up overpaid once every recorded payment is replayed in date order.
    live = [PaymentLike(p.amount_cents, p.paid_on) for p in live_payments(loan)]
    if raw_balance(terms_of(loan), live, now) < 0:
        db.session.rollback()
        return api_error(422, "exceeds_balance", "That amount would overpay the loan once interest is recomputed for its date.")
    # Snapshots are as of the payment date (what the borrower owed when they paid, and right after);
    # the loan's status reflects today.
    payment.balance_after_cents = compute_state(terms, history + [PaymentLike(amount, paid_on)], paid_on).balance_cents
    loan.status = "paid" if state_of(loan, now).is_paid_off else "active"
    try:
        db.session.commit()
    except IntegrityError:
        return _idempotency_race(idem, loan, amount, paid_on)
    db.session.refresh(payment)
    return {"payment": payment_json(payment, loan, g.tenant), "loan": loan_json(loan, detail=True)}, 201


@bp.get("/payments")
@require_tenant("admin")
def list_payments():
    limit = query_int("limit", default=50, lo=1, hi=200)
    rows = db.session.execute(
        db.select(Payment).where(Payment.tenant_id == g.tenant.id)
        .order_by(Payment.paid_on.desc(), Payment.created_at.desc()).limit(limit)
    ).scalars().all()
    return {"payments": [payment_json(p, p.loan, g.tenant) for p in rows]}


@bp.get("/payments/<payment_id>/receipt")
@require_tenant()
def receipt(payment_id):
    p = db.session.get(Payment, parse_uuid(payment_id))
    if p is None or p.tenant_id != g.tenant.id:
        return api_error(404, "not_found", "Receipt not found.")
    m = g.membership
    if m.role != "admin" and p.loan.borrower_id != m.borrower_id:
        return api_error(404, "not_found", "Receipt not found.")
    return _receipt_payload(p)


@bp.patch("/payments/<payment_id>")
@require_tenant("admin")
def update_payment(payment_id):
    p = db.session.get(Payment, parse_uuid(payment_id))
    if p is None or p.tenant_id != g.tenant.id:
        return api_error(404, "not_found", "Payment not found.")
    if p.voided_at is not None:
        return api_error(409, "already_voided", "Voided receipts can't be edited.")
    data = body()
    if "method" in data:
        p.method = req_choice(data, "method", PAYMENT_METHODS)
    if "note" in data:
        p.note = req_str(data, "note", max_len=500, required=False)
    db.session.commit()
    return {"payment": payment_json(p, p.loan, g.tenant)}


@bp.post("/payments/<payment_id>/void")
@require_tenant("admin")
def void_payment(payment_id):
    p = db.session.get(Payment, parse_uuid(payment_id))
    if p is None or p.tenant_id != g.tenant.id:
        return api_error(404, "not_found", "Payment not found.")
    loan = _locked_loan(str(p.loan_id))
    db.session.refresh(p)  # re-read under the loan lock so two concurrent voids can't both succeed
    if p.voided_at is not None:
        return api_error(409, "already_voided", "This payment is already voided.")
    data = body() if request.data else {}
    from ..models import utcnow
    p.voided_at = utcnow()
    p.void_reason = req_str(data, "reason", max_len=255, required=False)
    p.idempotency_key = None  # free the key so a genuine re-record with a new attempt isn't mistaken for a retry
    db.session.flush()
    db.session.refresh(loan)
    if loan.status != "cancelled":
        loan.status = "paid" if state_of(loan).is_paid_off else "active"
    db.session.commit()
    return {"payment": payment_json(p, loan, g.tenant), "loan": loan_json(loan, detail=True)}
