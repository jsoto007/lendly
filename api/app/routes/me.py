import secrets
from datetime import timedelta

from flask import Blueprint, current_app, g
from sqlalchemy.exc import IntegrityError

from ..auth import api_error, require_tenant, require_user
from ..extensions import db
from ..models import Borrower, Invite, Membership, Tenant, User, utcnow
from ..serializers import membership_json, tenant_json, user_json
from ._helpers import body, handle_bad_input, req_str

bp = Blueprint("me", __name__)
handle_bad_input(bp)

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(8))


@bp.get("/me")
@require_user
def me():
    return {"user": user_json(g.user), "memberships": [membership_json(m) for m in g.user.memberships]}


@bp.patch("/me")
@require_user
def update_me():
    data = body()
    name = req_str(data, "name", max_len=120, required=False)
    if name is not None:
        g.user.name = name
    db.session.commit()
    return {"user": user_json(g.user)}


@bp.post("/tenants")
@require_user
def create_tenant():
    data = body()
    name = req_str(data, "name", max_len=120)
    tenant = Tenant(name=name, owner_user_id=g.user.id)
    db.session.add(tenant)
    db.session.flush()
    membership = Membership(user_id=g.user.id, tenant_id=tenant.id, role="admin")
    db.session.add(membership)
    db.session.commit()
    return {"tenant": tenant_json(tenant), "membership": membership_json(membership)}, 201


@bp.get("/tenants/current")
@require_tenant()
def current_tenant():
    return {"tenant": tenant_json(g.tenant)}


@bp.patch("/tenants/current")
@require_tenant("admin")
def update_tenant():
    data = body()
    name = req_str(data, "name", max_len=120, required=False)
    if name is not None:
        g.tenant.name = name
    db.session.commit()
    return {"tenant": tenant_json(g.tenant)}


@bp.post("/invites/accept")
@require_user
def accept_invite():
    data = body()
    code = req_str(data, "code", max_len=16).upper().replace("-", "").replace(" ", "")
    db.session.execute(db.select(User).where(User.id == g.user.id).with_for_update())  # one accept at a time per user
    invite = db.session.execute(db.select(Invite).where(Invite.code == code).with_for_update()).scalar_one_or_none()
    if invite is None or invite.accepted_at is not None or invite.expires_at < utcnow():
        return api_error(404, "invite_invalid", "That invite code is invalid or has expired.")
    borrower = db.session.get(Borrower, invite.borrower_id, with_for_update=True)
    if borrower.user_id is not None and borrower.user_id != g.user.id:
        return api_error(409, "invite_taken", "This invite was already used by someone else.")
    existing = db.session.execute(
        db.select(Membership).where(Membership.user_id == g.user.id, Membership.tenant_id == invite.tenant_id)
    ).scalar_one_or_none()
    if existing is not None and existing.role != "borrower":
        return api_error(409, "already_member", "You already manage this workspace.")
    if existing is not None and existing.borrower_id not in (None, borrower.id):
        return api_error(409, "already_linked", "You're already linked to a different profile in this workspace.")
    if existing is None:
        existing = Membership(user_id=g.user.id, tenant_id=invite.tenant_id, role="borrower", borrower_id=borrower.id)
        db.session.add(existing)
    else:
        existing.borrower_id = borrower.id
    borrower.user_id = g.user.id
    if not borrower.email and g.user.email:
        borrower.email = g.user.email
    if not g.user.name:
        g.user.name = borrower.name
    invite.accepted_at = utcnow()
    invite.accepted_by_user_id = g.user.id
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error(409, "already_linked", "You're already linked to a different profile in this workspace.")
    db.session.refresh(existing)
    return {"membership": membership_json(existing)}
