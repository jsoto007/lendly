from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, g

from ..auth import require_tenant
from ..extensions import db
from ..models import Borrower, Loan, Payment
from ..serializers import add_months_safe, loan_json, payment_json, state_of, today

bp = Blueprint("dashboard", __name__)


@bp.get("/dashboard")
@require_tenant("admin")
def dashboard():
    today_ = today()
    loans = db.session.execute(
        db.select(Loan).where(Loan.tenant_id == g.tenant.id, Loan.status != "cancelled")
    ).scalars().all()
    borrower_count = db.session.execute(
        db.select(db.func.count(Borrower.id)).where(Borrower.tenant_id == g.tenant.id, Borrower.archived_at.is_(None))
    ).scalar_one()

    states = [(loan, state_of(loan, today_)) for loan in loans]
    active = [(l, s) for l, s in states if l.status == "active"]

    overdue, upcoming = [], []
    horizon = today_ + timedelta(days=30)
    for loan, s in active:
        if s.overdue_cents > 0:
            overdue.append(loan_json(loan))
            continue  # surfaced once, in the overdue section
        if s.next_due_date and today_ <= s.next_due_date <= horizon:
            upcoming.append({
                "loan_id": str(loan.id),
                "title": loan.title,
                "borrower_id": str(loan.borrower_id),
                "borrower_name": loan.borrower.name,
                "due_date": s.next_due_date.isoformat(),
                "amount_cents": s.next_due_cents,
            })
        elif s.next_due_date is None and s.balance_cents > 0 and s.overdue_cents == 0:
            # Past term with a balance that isn't schedule-overdue (e.g. compound late accrual).
            upcoming.append({
                "loan_id": str(loan.id), "title": loan.title, "borrower_id": str(loan.borrower_id),
                "borrower_name": loan.borrower.name, "due_date": today_.isoformat(), "amount_cents": s.balance_cents,
            })
    overdue.sort(key=lambda l: (-l["state"]["days_overdue"], -l["state"]["overdue_cents"]))
    upcoming.sort(key=lambda u: (u["due_date"], u["borrower_name"]))

    recent = db.session.execute(
        db.select(Payment).where(Payment.tenant_id == g.tenant.id, Payment.voided_at.is_(None))
        .order_by(Payment.paid_on.desc(), Payment.created_at.desc()).limit(8)
    ).scalars().all()

    # Collected per month, last 6 months including this one.
    first_month = add_months_safe(today_.replace(day=1), -5)
    monthly = defaultdict(int)
    for p in db.session.execute(
        db.select(Payment).where(Payment.tenant_id == g.tenant.id, Payment.voided_at.is_(None), Payment.paid_on >= first_month)
    ).scalars():
        monthly[p.paid_on.strftime("%Y-%m")] += p.amount_cents
    series = []
    for k in range(6):
        m = add_months_safe(first_month, k)
        key = m.strftime("%Y-%m")
        series.append({"month": key, "cents": monthly.get(key, 0)})

    return {
        "totals": {
            "lent_cents": sum(l.principal_cents for l, _ in states),
            "outstanding_cents": sum(s.balance_cents for _, s in active),
            "collected_cents": sum(s.paid_cents for _, s in states),
            "projected_interest_cents": sum(s.interest_cents for _, s in states),
            "overdue_cents": sum(s.overdue_cents for _, s in active),
            "active_loans": len(active),
            "paid_loans": sum(1 for l, _ in states if l.status == "paid"),
            "borrowers": borrower_count,
        },
        "overdue": overdue,
        "upcoming": upcoming,
        "recent_payments": [payment_json(p, p.loan, g.tenant) for p in recent],
        "monthly_collected": series,
        "as_of": today_.isoformat(),
    }
