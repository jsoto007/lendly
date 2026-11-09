import re

import jwt
from flask import Blueprint, current_app

from .. import mailer
from ..auth import (api_error, client_ip, code_requests_exhausted, create_email_code, ip_requests_exhausted,
                    issue_token, user_from_apple_claims, verify_apple_identity_token, verify_email_code)
from ..serializers import membership_json, user_json
from ._helpers import body, handle_bad_input, req_str

bp = Blueprint("auth", __name__)
handle_bad_input(bp)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _session_payload(user):
    return {
        "token": issue_token(user),
        "user": user_json(user),
        "memberships": [membership_json(m) for m in user.memberships],
    }


@bp.post("/auth/email/request")
def email_request():
    data = body()
    email = req_str(data, "email").lower()
    if not EMAIL_RE.match(email):
        return api_error(422, "invalid", "Enter a valid email address.")
    cfg = current_app.config
    if ip_requests_exhausted(client_ip()):
        return api_error(429, "too_many_requests", "Too many requests. Try again in a few minutes.")
    if code_requests_exhausted(email):
        return api_error(429, "too_many_requests", "Too many codes requested for this email. Try again in {minutes} minutes.",
                         minutes=cfg["OTP_REQUEST_WINDOW_MINUTES"])
    if cfg["REVIEW_LOGIN_EMAIL"] and cfg["REVIEW_LOGIN_CODE"] and email == cfg["REVIEW_LOGIN_EMAIL"]:
        # App Review demo account: fixed code, nothing e-mailed, works without Mailgun.
        create_email_code(email, code=cfg["REVIEW_LOGIN_CODE"])
        return {"sent": True}
    if not mailer.is_configured() and not cfg["DEV_RETURN_OTP"]:
        current_app.logger.error("email login requested but MAILGUN_* is not configured")
        return api_error(503, "email_unavailable", "Email sign-in isn't set up yet. Try Sign in with Apple.")
    code = create_email_code(email)
    out = {"sent": True}
    if mailer.is_configured():
        try:
            mailer.send_login_code(email, code)
        except mailer.MailError:
            return api_error(502, "email_failed", "We couldn't send the code. Try again in a minute.")
    if current_app.config["DEV_RETURN_OTP"]:
        out["dev_code"] = code  # local dev only; never true in production
    return out


@bp.post("/auth/email/verify")
def email_verify():
    data = body()
    email = req_str(data, "email").lower()
    code = req_str(data, "code", max_len=12)
    user = verify_email_code(email, code)
    if user is None:
        return api_error(401, "bad_code", "That code is wrong or expired.")
    return _session_payload(user)


@bp.post("/auth/apple")
def apple():
    data = body()
    token = req_str(data, "identity_token", max_len=8192)
    name = req_str(data, "name", max_len=120, required=False)
    try:
        claims = verify_apple_identity_token(token)
    except jwt.PyJWTError as e:
        current_app.logger.warning("apple token rejected: %s", e)
        return api_error(401, "apple_rejected", "Apple sign-in could not be verified.")
    user = user_from_apple_claims(claims, name)
    return _session_payload(user)
