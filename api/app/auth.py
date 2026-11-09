"""JWT sessions, Sign in with Apple verification, and email one-time codes."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
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


def create_email_code(email: str, code: str | None = None) -> str:
    """Issue a one-time code for `email`. `code` is only passed for the App Review demo login."""
    email = email.strip().lower()
    code = code or f"{secrets.randbelow(1_000_000):06d}"
    # Only one live code per address.
    db.session.execute(
        db.update(OtpCode).where(OtpCode.email == email, OtpCode.consumed_at.is_(None)).values(consumed_at=utcnow())
    )
    db.session.add(OtpCode(
        email=email,
        inbox=inbox_key(email),
        code_hash=_hash_code(email, code),
        expires_at=utcnow() + timedelta(minutes=current_app.config["OTP_TTL_MINUTES"]),
    ))
    db.session.commit()
    current_app.logger.info("email code issued for %s", email)
    return code


def inbox_key(email: str) -> str:
    """The mailbox an address really lands in, for rate limiting: lower-cased, and for Gmail
    with dots and +tags removed so victim+1@gmail.com can't dodge victim@gmail.com's limit."""
    email = email.strip().lower()
    local, _, domain = email.rpartition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    else:
        local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def code_requests_exhausted(email: str) -> bool:
    """True once this inbox has asked for OTP_REQUEST_LIMIT codes inside the window (consumed or
    not), so one mailbox can't be flooded with login e-mails. Takes a transaction-scoped advisory
    lock on the inbox so concurrent requests count each other (no count-then-insert gap); the
    lock is released by the commit in create_email_code or the request's rollback."""
    cfg = current_app.config
    key = inbox_key(email)
    db.session.execute(db.text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "otp:" + key})
    since = utcnow() - timedelta(minutes=cfg["OTP_REQUEST_WINDOW_MINUTES"])
    n = db.session.execute(
        db.select(db.func.count(OtpCode.id)).where(OtpCode.inbox == key, OtpCode.created_at >= since)
    ).scalar_one()
    return n >= cfg["OTP_REQUEST_LIMIT"]


_ip_hits: dict[str, list[float]] = {}
_ip_lock = threading.Lock()


def client_ip() -> str:
    """The proxy-appended address when behind Render, else the socket peer. The last hop in
    X-Forwarded-For is the one the proxy added, so a client can't spoof it with its own header."""
    route = request.access_route
    return route[-1] if route else (request.remote_addr or "unknown")


def ip_requests_exhausted(ip: str) -> bool:
    """Best-effort per-IP limit on code requests (in memory, per worker)."""
    cfg = current_app.config
    window = cfg["OTP_REQUEST_WINDOW_MINUTES"] * 60
    now = time.monotonic()
    with _ip_lock:
        hits = [t for t in _ip_hits.get(ip, []) if now - t < window]
        if len(hits) >= cfg["OTP_IP_LIMIT"]:
            _ip_hits[ip] = hits
            return True
        hits.append(now)
        _ip_hits[ip] = hits
        if len(_ip_hits) > 10_000:  # keep the table bounded
            for stale in [k for k, v in _ip_hits.items() if not v or now - v[-1] >= window]:
                _ip_hits.pop(stale, None)
        return False


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
