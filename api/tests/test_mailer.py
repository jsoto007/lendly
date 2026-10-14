import pytest

from app import mailer


@pytest.fixture
def mail_configured(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAILGUN_API_KEY", "key-test")
    monkeypatch.setitem(app.config, "MAILGUN_DOMAIN", "mg.example.com")
    monkeypatch.setitem(app.config, "MAILGUN_FROM", "Lendly <no-reply@example.com>")


def test_login_code_is_emailed_and_not_returned_in_production(app, client, mail_configured, monkeypatch):
    sent = {}
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.update(to=to, subject=subject, text=text, html=html) or "<id>")
    monkeypatch.setitem(app.config, "DEV_RETURN_OTP", False)
    r = client.post("/api/auth/email/request", json={"email": "Person@Example.com"})
    assert r.status_code == 200 and r.json == {"sent": True}
    assert sent["to"] == "person@example.com"
    code = sent["subject"].split()[0]
    assert len(code) == 6 and code.isdigit() and code in sent["text"] and code in sent["html"]
    # the emailed code actually works
    r = client.post("/api/auth/email/verify", json={"email": "person@example.com", "code": code})
    assert r.status_code == 200 and "token" in r.json


def test_login_email_is_spanish_when_requested(app, client, mail_configured, monkeypatch):
    sent = {}
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.update(subject=subject) or "")
    r = client.post("/api/auth/email/request", json={"email": "p@example.com"}, headers={"Accept-Language": "es"})
    assert r.status_code == 200
    assert sent["subject"].endswith("es tu código de Lendly")


def test_unconfigured_email_in_production_is_a_clear_503(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "DEV_RETURN_OTP", False)
    r = client.post("/api/auth/email/request", json={"email": "p@example.com"})
    assert r.status_code == 503 and r.json["error"]["code"] == "email_unavailable"


def test_mailgun_failure_is_a_502_not_a_500(app, client, mail_configured, monkeypatch):
    def boom(*a, **k):
        raise mailer.MailError("down")
    monkeypatch.setattr(mailer, "send", boom)
    r = client.post("/api/auth/email/request", json={"email": "p@example.com"})
    assert r.status_code == 502 and r.json["error"]["code"] == "email_failed"


def test_send_builds_a_mailgun_request(app, mail_configured, monkeypatch):
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"id": "<msg@mg>"}'

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = req.data.decode()
        return Resp()

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    with app.test_request_context():
        assert mailer.send("to@example.com", "Hi", "text") == "<msg@mg>"
    assert captured["url"] == "https://api.mailgun.net/v3/mg.example.com/messages"
    assert captured["auth"].startswith("Basic ")
    assert "to=to%40example.com" in captured["body"] and "from=Lendly" in captured["body"]
