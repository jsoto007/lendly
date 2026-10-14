from datetime import timedelta

from flask import Blueprint, current_app, g, request

from ..auth import api_error, require_tenant
from ..extensions import db
from ..models import Borrower, Invite, Loan, utcnow
from ..serializers import borrower_json, invite_json, loan_json
from ._helpers import body, handle_bad_input, parse_uuid, req_bool, req_str
from .me import new_invite_code

bp = Blueprint("borrowers", __name__)
handle_bad_input(bp)


def _get_borrower(borrower_id):
    b = db.session.get(Borrower, parse_uuid(borrower_id))
    if b is None or b.tenant_id != g.tenant.id:
        return None
    return b


def _loans_for(b: Borrower) -> list[Loan]:
    return db.session.execute(
        db.select(Loan).where(Loan.borrower_id == b.id).order_by(Loan.created_at.desc())
    ).scalars().all()


@bp.get("/borrowers")
@require_tenant("admin")
def list_borrowers():
    q = db.select(Borrower).where(Borrower.tenant_id == g.tenant.id)
    if request.args.get("include_archived") != "true":
        q = q.where(Borrower.archived_at.is_(None))
    rows = db.session.execute(q.order_by(Borrower.name)).scalars().all()
    return {"borrowers": [borrower_json(b, _loans_for(b)) for b in rows]}


@bp.post("/borrowers")
@require_tenant("admin")
def create_borrower():
    data = body()
    b = Borrower(
        tenant_id=g.tenant.id,
        name=req_str(data, "name", max_len=120),
        email=(req_str(data, "email", required=False) or None),
        phone=req_str(data, "phone", max_len=40, required=False),
        notes=req_str(data, "notes", max_len=2000, required=False),
    )
    if b.email:
        b.email = b.email.lower()
    db.session.add(b)
    db.session.commit()
    return {"borrower": borrower_json(b, [])}, 201


@bp.get("/borrowers/<borrower_id>")
@require_tenant("admin")
def get_borrower(borrower_id):
    b = _get_borrower(borrower_id)
    if b is None:
        return api_error(404, "not_found", "Borrower not found.")
    loans = _loans_for(b)
    active_invite = db.session.execute(
        db.select(Invite).where(Invite.borrower_id == b.id, Invite.accepted_at.is_(None), Invite.expires_at > utcnow())
        .order_by(Invite.created_at.desc())
    ).scalars().first()
    return {
        "borrower": borrower_json(b, loans),
        "loans": [loan_json(l) for l in loans],
        "invite": invite_json(active_invite, current_app.config["INVITE_LINK_BASE"]) if active_invite else None,
    }


@bp.patch("/borrowers/<borrower_id>")
@require_tenant("admin")
def update_borrower(borrower_id):
    b = _get_borrower(borrower_id)
    if b is None:
        return api_error(404, "not_found", "Borrower not found.")
    data = body()
    if "name" in data:
        b.name = req_str(data, "name", max_len=120)
    if "email" in data:
        email = req_str(data, "email", required=False)
        b.email = email.lower() if email else None
    if "phone" in data:
        b.phone = req_str(data, "phone", max_len=40, required=False)
    if "notes" in data:
        b.notes = req_str(data, "notes", max_len=2000, required=False)
    if "archived" in data:
        b.archived_at = utcnow() if req_bool(data, "archived") else None
    db.session.commit()
    return {"borrower": borrower_json(b, _loans_for(b))}


@bp.post("/borrowers/<borrower_id>/invites")
@require_tenant("admin")
def create_invite(borrower_id):
    b = _get_borrower(borrower_id)
    if b is None:
        return api_error(404, "not_found", "Borrower not found.")
    if b.archived_at is not None:
        return api_error(409, "borrower_archived", "Unarchive this borrower before inviting them.")
    if b.user_id is not None:
        return api_error(409, "already_linked", f"{b.name} already has access.")
    # Only one live invite per borrower.
    db.session.execute(
        db.update(Invite).where(Invite.borrower_id == b.id, Invite.accepted_at.is_(None)).values(expires_at=utcnow())
    )
    invite = Invite(
        tenant_id=g.tenant.id,
        borrower_id=b.id,
        code=new_invite_code(),
        expires_at=utcnow() + timedelta(days=current_app.config["INVITE_TTL_DAYS"]),
    )
    db.session.add(invite)
    db.session.commit()
    return {"invite": invite_json(invite, current_app.config["INVITE_LINK_BASE"])}, 201
