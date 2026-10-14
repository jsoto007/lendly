from __future__ import annotations

from dataclasses import asdict
from datetime import date

from flask import g, has_request_context

from .models import Borrower, Invite, Loan, Membership, Payment, Tenant, User
from .services.schedule import Installment, LoanState, LoanTerms, PaymentLike, build_schedule, compute_state


def terms_of(loan: Loan) -> LoanTerms:
    return LoanTerms(
        principal_cents=loan.principal_cents,
        interest_type=loan.interest_type,
        rate_bps=loan.rate_bps,
        fixed_fee_cents=loan.fixed_fee_cents,
        fixed_fee_per_period=loan.fixed_fee_per_period,
        schedule=loan.schedule,
        term_periods=loan.term_periods,
        start_date=loan.start_date,
    )


def live_payments(loan: Loan) -> list[Payment]:
    return [p for p in loan.payments if p.voided_at is None]


def today() -> date:
    if has_request_context():
        from .routes._helpers import local_today
        return local_today()
    return date.today()


def _viewer_is_admin() -> bool:
    if not has_request_context():
        return True
    m = getattr(g, "membership", None)
    return m is None or m.role == "admin"


def state_of(loan: Loan, as_of: date | None = None) -> LoanState:
    as_of = as_of or today()
    pays = [PaymentLike(p.amount_cents, p.paid_on) for p in live_payments(loan)]
    return compute_state(terms_of(loan), pays, as_of)


def user_json(u: User) -> dict:
    return {"id": str(u.id), "email": u.email, "name": u.name, "has_apple": u.apple_sub is not None}


def membership_json(m: Membership) -> dict:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "tenant_name": m.tenant.name,
        "role": m.role,
        "borrower_id": str(m.borrower_id) if m.borrower_id else None,
        "currency": m.tenant.currency,
    }


def tenant_json(t: Tenant) -> dict:
    return {"id": str(t.id), "name": t.name, "currency": t.currency, "created_at": t.created_at.isoformat()}


def borrower_json(b: Borrower, loans: list[Loan] | None = None) -> dict:
    out = {
        "id": str(b.id),
        "name": b.name,
        "email": b.email,
        "phone": b.phone,
        "notes": b.notes if _viewer_is_admin() else None,
        "linked": b.user_id is not None,
        "archived": b.archived_at is not None,
        "created_at": b.created_at.isoformat(),
    }
    if loans is not None:
        states = [(l, state_of(l)) for l in loans if l.status != "cancelled"]
        active = [s for l, s in states if l.status == "active"]
        out["summary"] = {
            "active_loans": len(active),
            "total_loans": len(loans),
            "outstanding_cents": sum(s.balance_cents for s in active),
            "overdue_cents": sum(s.overdue_cents for s in active),
            "lent_cents": sum(l.principal_cents for l, _ in states),
            "paid_cents": sum(s.paid_cents for _, s in states),
        }
    return out


def invite_json(i: Invite, link_base: str) -> dict:
    return {
        "id": str(i.id),
        "code": i.code,
        "link": f"{link_base}/{i.code}",
        "borrower_id": str(i.borrower_id),
        "expires_at": i.expires_at.isoformat(),
        "accepted_at": i.accepted_at.isoformat() if i.accepted_at else None,
    }


def installment_json(i: Installment, paid_cents: int, as_of: date, *, is_last: bool = False,
                     balance_cents: int = 0, cancelled: bool = False) -> dict:
    covered = paid_cents >= i.cumulative_due_cents
    partial = (not covered) and paid_cents > i.cumulative_due_cents - i.amount_cents
    if cancelled:
        status = "cancelled"
    elif covered and is_last and balance_cents > 0:
        status, partial = "overdue", True  # schedule covered but late interest still owed
    elif covered:
        status = "paid"
    elif i.due_date < as_of:
        status = "overdue"
    else:
        status = "upcoming"
    return {
        "number": i.number,
        "due_date": i.due_date.isoformat(),
        "amount_cents": i.amount_cents,
        "cumulative_due_cents": i.cumulative_due_cents,
        "status": status,
        "partial": partial,
    }


def state_json(s: LoanState) -> dict:
    d = asdict(s)
    d["next_due_date"] = s.next_due_date.isoformat() if s.next_due_date else None
    return d


def payment_json(p: Payment, loan: Loan | None = None, tenant: Tenant | None = None) -> dict:
    out = {
        "id": str(p.id),
        "loan_id": str(p.loan_id),
        "amount_cents": p.amount_cents,
        "paid_on": p.paid_on.isoformat(),
        "method": p.method,
        "note": p.note,
        "receipt_number": p.receipt_number,
        "receipt_code": f"R-{p.receipt_number:05d}",
        "balance_before_cents": p.balance_before_cents,
        "balance_after_cents": p.balance_after_cents,
        "voided": p.voided_at is not None,
        "voided_at": p.voided_at.isoformat() if p.voided_at else None,
        "void_reason": p.void_reason,
        "created_at": p.created_at.isoformat(),
    }
    if loan is not None:
        out["loan_title"] = loan.title
        out["borrower_name"] = loan.borrower.name
    if tenant is not None:
        out["lender_name"] = tenant.name
        out["currency"] = tenant.currency
    return out


def loan_json(loan: Loan, detail: bool = False, as_of: date | None = None) -> dict:
    as_of = as_of or today()
    state = state_of(loan, as_of)
    cancelled = loan.status == "cancelled"
    if cancelled:
        # A cancelled loan is frozen: nothing is due or overdue.
        state.overdue_cents, state.days_overdue = 0, 0
        state.next_due_date, state.next_due_cents = None, None
    out = {
        "id": str(loan.id),
        "borrower_id": str(loan.borrower_id),
        "borrower_name": loan.borrower.name,
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
        "notes": loan.notes if _viewer_is_admin() else None,
        "created_at": loan.created_at.isoformat(),
        "state": state_json(state),
    }
    if detail:
        paid = state.paid_cents
        schedule = build_schedule(terms_of(loan))
        out["installments"] = [
            installment_json(i, paid, as_of, is_last=(i is schedule[-1]), balance_cents=state.balance_cents, cancelled=cancelled)
            for i in schedule
        ]
        out["payments"] = [payment_json(p) for p in sorted(loan.payments, key=lambda p: (p.paid_on, p.created_at), reverse=True)]
    return out


def add_months_safe(d: date, months: int) -> date:
    from .services.schedule import add_months
    return add_months(d, months)
