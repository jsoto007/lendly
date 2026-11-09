"""Outbound email through Mailgun (same provider and variable names as the emailer project).

Configured with MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM and optional MAILGUN_BASE_URL
(https://api.mailgun.net for US, https://api.eu.mailgun.net for EU). When unconfigured,
`is_configured()` is False and the login route falls back to dev mode or refuses.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from flask import current_app

from .i18n import language


class MailError(Exception):
    pass


def is_configured() -> bool:
    c = current_app.config
    return bool(c.get("MAILGUN_API_KEY") and c.get("MAILGUN_DOMAIN") and c.get("MAILGUN_FROM"))


def send(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Send one email; returns the Mailgun message id. Raises MailError on failure."""
    c = current_app.config
    url = f"{c['MAILGUN_BASE_URL'].rstrip('/')}/v3/{c['MAILGUN_DOMAIN']}/messages"
    fields = {"from": c["MAILGUN_FROM"], "to": to, "subject": subject, "text": text}
    if html:
        fields["html"] = html
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    token = base64.b64encode(f"api:{c['MAILGUN_API_KEY']}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode() or "{}")
            return body.get("id", "")
    except urllib.error.HTTPError as e:
        current_app.logger.error("mailgun %s: %s", e.code, e.read()[:300])
        raise MailError(f"mailgun rejected the message ({e.code})")
    except (urllib.error.URLError, TimeoutError) as e:
        current_app.logger.error("mailgun unreachable: %s", e)
        raise MailError("mailgun unreachable")


def send_login_code(email: str, code: str) -> str:
    minutes = current_app.config["OTP_TTL_MINUTES"]
    if language() == "es":
        subject = f"{code} es tu código de Lendly"
        text = (f"Tu código de inicio de sesión de Lendly es {code}. Vence en {minutes} minutos.\n\n"
                "Si no intentaste iniciar sesión, ignora este correo.")
        heading, body, note = "Tu código de inicio de sesión", f"Vence en {minutes} minutos.", "Si no intentaste iniciar sesión, ignora este correo."
    else:
        subject = f"{code} is your Lendly code"
        text = (f"Your Lendly sign-in code is {code}. It expires in {minutes} minutes.\n\n"
                "If you didn't try to sign in, you can ignore this email.")
        heading, body, note = "Your sign-in code", f"It expires in {minutes} minutes.", "If you didn't try to sign in, you can ignore this email."
    html = f"""<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:420px;margin:0 auto;padding:24px">
  <p style="font-size:14px;color:#6b7280;margin:0 0 8px">Lendly</p>
  <h1 style="font-size:20px;margin:0 0 16px">{heading}</h1>
  <p style="font-size:32px;letter-spacing:6px;font-weight:700;margin:0 0 16px">{code}</p>
  <p style="font-size:14px;color:#374151;margin:0 0 24px">{body}</p>
  <p style="font-size:12px;color:#9ca3af;margin:0">{note}</p>
</div>"""
    return send(email, subject, text, html)
