from datetime import date

from flask import Blueprint, g, request

from ..auth import api_error, require_tenant
from ..extensions import db
from ..models import INTEREST_TYPES, LOAN_STATUSES, SCHEDULES, Borrower, Loan
from ..serializers import installment_json, live_payments, loan_json, state_json, state_of, today
from ..services.schedule import LoanTerms, build_schedule, compute_state, validate_terms
from ._helpers import (MAX_CENTS, BadInput, body, handle_bad_input, parse_uuid, req_bool, req_choice,
                       req_date, req_int, req_str)

bp = Blueprint("loans", __name__)
handle_bad_input(bp)


def terms_from_body(data: dict, existing: Loan | None = None) -> LoanTerms:
    def pick(key, fn, *a, **kw):
        # On edit, an absent key or an explicit null both mean "keep the current value".
        if existing is not None and data.get(key) is None:
            return getattr(existing, key)
        return fn(data, key, *a, **kw)

    interest_type = pick("interest_type", req_choice, INTEREST_TYPES)
    t = LoanTerms(
        principal_cents=pick("principal_cents", req_int, minimum=1, maximum=MAX_CENTS),
        interest_type=interest_type,
        rate_bps=pick("rate_bps", req_int, required=False, default=0, minimum=0, maximum=100_000),
        fixed_fee_cents=pick("fixed_fee_cents", req_int, required=False, default=0, minimum=0, maximum=MAX_CENTS),
        fixed_fee_per_period=pick("fixed_fee_per_period", req_bool, default=False),
        schedule=pick("schedule", req_choice, SCHEDULES),
        term_periods=pick("term_periods", req_int, minimum=1),
        start_date=pick("start_date", req_date, required=False, default=today()),
    )
    errors = validate_terms(t)
    if errors:
        from ..i18n import _
        raise BadInput("; ".join(_(e) for e in errors))
    return t


def get_loan_for_admin(loan_id, lock: bool = False) -> Loan | None:
    q = db.select(Loan).where(Loan.id == parse_uuid(loan_id), Loan.tenant_id == g.tenant.id)
    if lock:
        q = q.with_for_update()  # same row lock record_payment takes, so terms can't change under a payment
    loan = db.session.execute(q).scalar_one_or_none()
    if loan is not None and lock:
        db.session.refresh(loan)  # see payments committed by anyone who held the lock before us
    return loan


def loan_visible_to_member(loan: Loan) -> bool:
    m = g.membership
    if m.role == "admin":
        return True
    return m.borrower_id is not None and loan.borrower_id == m.borrower_id


@bp.post("/loans/preview")
@require_tenant("admin")
def preview():
    t = terms_from_body(body())
    schedule = build_schedule(t)
    state = compute_state(t, [], t.start_date)
    return {
        "state": state_json(state),
        "installments": [installment_json(i, 0, t.start_date) for i in schedule],
        "end_date": schedule[-1].due_date.isoformat(),
    }


@bp.get("/loans")
@require_tenant("admin")
def list_loans():
    q = db.select(Loan).where(Loan.tenant_id == g.tenant.id)
    status = request.args.get("status")
    if status:
        if status not in LOAN_STATUSES:
            raise BadInput("Unknown status filter.")
        q = q.where(Loan.status == status)
    if request.args.get("borrower_id"):
        q = q.where(Loan.borrower_id == parse_uuid(request.args["borrower_id"]))
    loans = db.session.execute(q.order_by(Loan.created_at.desc())).scalars().all()
    return {"loans": [loan_json(l) for l in loans]}


@bp.post("/loans")
@require_tenant("admin")
def create_loan():
    data = body()
    borrower = db.session.get(Borrower, parse_uuid(data.get("borrower_id", "")))
    if borrower is None or borrower.tenant_id != g.tenant.id:
        return api_error(404, "not_found", "Borrower not found.")
    if borrower.archived_at is not None:
        return api_error(409, "borrower_archived", "Unarchive this borrower before creating a loan.")
    t = terms_from_body(data)
    loan = Loan(
        tenant_id=g.tenant.id,
        borrower_id=borrower.id,
        title=req_str(data, "title", max_len=120, required=False) or "Loan",
        principal_cents=t.principal_cents,
        interest_type=t.interest_type,
        rate_bps=t.rate_bps,
        fixed_fee_cents=t.fixed_fee_cents,
        fixed_fee_per_period=t.fixed_fee_per_period,
        schedule=t.schedule,
        term_periods=t.term_periods,
        start_date=t.start_date,
        notes=req_str(data, "notes", max_len=2000, required=False),
    )
    db.session.add(loan)
    db.session.flush()
    payload = {"loan": loan_json(loan, detail=True)}  # serialize before commit so a bad loan never persists
    db.session.commit()
    return payload, 201


@bp.get("/loans/<loan_id>")
@require_tenant()
def get_loan(loan_id):
    loan = db.session.get(Loan, parse_uuid(loan_id))
    if loan is None or loan.tenant_id != g.tenant.id or not loan_visible_to_member(loan):
        return api_error(404, "not_found", "Loan not found.")
    if g.membership.role != "admin" and loan.status == "cancelled":
        return api_error(404, "not_found", "Loan not found.")  # matches the portal, which hides cancelled loans
    return {"loan": loan_json(loan, detail=True)}


@bp.patch("/loans/<loan_id>")
@require_tenant("admin")
def update_loan(loan_id):
    loan = get_loan_for_admin(loan_id, lock=True)
    if loan is None:
        return api_error(404, "not_found", "Loan not found.")
    data = body()
    term_keys = {"principal_cents", "interest_type", "rate_bps", "fixed_fee_cents",
                 "fixed_fee_per_period", "schedule", "term_periods", "start_date"}
    if term_keys & data.keys():
        if live_payments(loan):
            return api_error(409, "has_payments", "Terms are locked once a payment has been recorded. Void the payments first.")
        t = terms_from_body(data, existing=loan)
        for key in term_keys:
            setattr(loan, key, getattr(t, key))
    if "title" in data:
        loan.title = req_str(data, "title", max_len=120)
    if "notes" in data:
        loan.notes = req_str(data, "notes", max_len=2000, required=False)
    if "status" in data:
        status = req_choice(data, "status", ("active", "cancelled"))
        if status == "active" and loan.status == "cancelled":
            loan.status = "active"
        elif status == "cancelled":
            if live_payments(loan):
                return api_error(409, "has_payments", "Void the recorded payments before cancelling this loan.")
            loan.status = "cancelled"
    db.session.flush()
    # Keep the derived "paid" status honest after term edits.
    if loan.status != "cancelled":
        loan.status = "paid" if state_of(loan).is_paid_off else "active"
    db.session.commit()
    return {"loan": loan_json(loan, detail=True)}


@bp.delete("/loans/<loan_id>")
@require_tenant("admin")
def delete_loan(loan_id):
    loan = get_loan_for_admin(loan_id, lock=True)
    if loan is None:
        return api_error(404, "not_found", "Loan not found.")
    if loan.payments:
        return api_error(409, "has_payments", "Loans with payment history can't be deleted. Cancel it instead.")
    db.session.delete(loan)
    db.session.commit()
    return "", 204
