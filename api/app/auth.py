"""JWT sessions, Sign in with Apple verification, and email one-time codes."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from .extensions import db
from .models import Membership, OtpCode, Tenant, User, utcnow

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_jwks_client: jwt.PyJWKClient | None = None


def api_error(status: int, code: str, message: str, **kwargs):
    from .i18n import _
    return jsonify({"error": {"code": code, "message": _(message, **kwargs)}}), status


# ---------------------------------------------------------------- JWT ---------
def issue_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=current_app.config["JWT_TTL_DAYS"])).timestamp()),
    }
    return jwt.encode(payload, current_app.config["JWT_SECRET"], algorithm="HS256")


def user_from_token(token: str) -> User | None:
    try:
        payload = jwt.decode(token, current_app.config["JWT_SECRET"], algorithms=["HS256"])
        return db.session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return api_error(401, "unauthenticated", "Sign in required.")
        user = user_from_token(header[7:].strip())
        if user is None:
            return api_error(401, "unauthenticated", "Session expired. Sign in again.")
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def require_tenant(*roles: str):
    """Resolve the X-Tenant-Id header into g.tenant / g.membership and enforce role."""
    def decorator(fn):
        @wraps(fn)
        @require_user
        def wrapper(*args, **kwargs):
            raw = request.headers.get("X-Tenant-Id", "")
            try:
                tenant_id = uuid.UUID(raw)
            except ValueError:
                return api_error(400, "tenant_required", "X-Tenant-Id header is required.")
            membership = db.session.execute(
                db.select(Membership).where(Membership.user_id == g.user.id, Membership.tenant_id == tenant_id)
            ).scalar_one_or_none()
            if membership is None:
                return api_error(403, "forbidden", "You are not a member of this workspace.")
            if roles and membership.role not in roles:
                return api_error(403, "forbidden", "This action needs the lender role.")
            g.membership = membership
            g.tenant = db.session.get(Tenant, tenant_id)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------- Email codes -------
def _hash_code(email: str, code: str) -> str:
    secret = current_app.config["JWT_SECRET"].encode()
    return hmac.new(secret, f"{email.lower()}:{code}".encode(), hashlib.sha256).hexdigest()


def create_email_code(email: str) -> str:
    email = email.strip().lower()
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Only one live code per address.
    db.session.execute(
        db.update(OtpCode).where(OtpCode.email == email, OtpCode.consumed_at.is_(None)).values(consumed_at=utcnow())
    )
    db.session.add(OtpCode(
        email=email,
        code_hash=_hash_code(email, code),
        expires_at=utcnow() + timedelta(minutes=current_app.config["OTP_TTL_MINUTES"]),
    ))
    db.session.commit()
    current_app.logger.info("email code issued for %s", email)
    return code


def verify_email_code(email: str, code: str) -> User | None:
    email = email.strip().lower()
    otp = db.session.execute(
        db.select(OtpCode)
        .where(OtpCode.email == email, OtpCode.consumed_at.is_(None), OtpCode.expires_at > utcnow())
        .order_by(OtpCode.created_at.desc())
        .with_for_update()
    ).scalars().first()
    if otp is None:
        return None
    otp.attempts += 1
    if otp.attempts > 5:
        otp.consumed_at = utcnow()
        db.session.commit()
        return None
    if not hmac.compare_digest(otp.code_hash, _hash_code(email, code.strip())):
        db.session.commit()
        return None
    otp.consumed_at = utcnow()
    user = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email)
        db.session.add(user)
    db.session.commit()
    return user


# ------------------------------------------------------- Sign in with Apple ---
def verify_apple_identity_token(identity_token: str) -> dict:
    """Validate an Apple identity token against Apple's public keys.
    Raises jwt.PyJWTError on any failure."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(APPLE_JWKS_URL, cache_keys=True)
    signing_key = _jwks_client.get_signing_key_from_jwt(identity_token)
    return jwt.decode(
        identity_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=current_app.config["APPLE_BUNDLE_ID"],
        issuer=APPLE_ISSUER,
    )


def user_from_apple_claims(claims: dict, name: str | None) -> User:
    sub = claims["sub"]
    email = (claims.get("email") or "").strip().lower() or None
    user = db.session.execute(db.select(User).where(User.apple_sub == sub)).scalar_one_or_none()
    if user is None and email:
        # Same person who previously used the email code flow.
        user = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
        if user is not None:
            user.apple_sub = sub
    if user is None:
        user = User(apple_sub=sub, email=email)
        db.session.add(user)
    if name and not user.name:
        user.name = name.strip()[:120]
    db.session.commit()
    return user
