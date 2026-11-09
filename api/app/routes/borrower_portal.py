from flask import Blueprint, g

from ..auth import api_error, require_tenant
from ..extensions import db
from ..models import Borrower, Loan
from ..serializers import borrower_json, loan_json, payment_json, state_of

bp = Blueprint("borrower_portal", __name__)


@bp.get("/borrower/overview")
@require_tenant("borrower")
def overview():
    """Read-only view for the person who took the loans."""
    b = db.session.get(Borrower, g.membership.borrower_id)
    if b is None:
        return api_error(404, "not_found", "Borrower profile not found.")
    loans = db.session.execute(
        db.select(Loan).where(Loan.borrower_id == b.id, Loan.status != "cancelled").order_by(Loan.created_at.desc())
    ).scalars().all()
    payments = []
    for loan in loans:
        for p in loan.payments:
            if p.voided_at is None:
                payments.append(payment_json(p, loan, g.tenant))
    payments.sort(key=lambda p: (p["paid_on"], p["created_at"]), reverse=True)
    return {
        "borrower": borrower_json(b, loans),
        "lender": {"id": str(g.tenant.id), "name": g.tenant.name, "currency": g.tenant.currency},
        "loans": [loan_json(l, detail=True) for l in loans],
        "payments": payments,
    }
