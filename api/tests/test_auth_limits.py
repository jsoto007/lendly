"""Login-code request limits and the App Review demo login."""
import pytest

from app import auth as auth_module


@pytest.fixture(autouse=True)
def reset_ip_table():
    auth_module._ip_hits.clear()
    yield
    auth_module._ip_hits.clear()


def test_per_email_code_requests_are_limited(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_REQUEST_LIMIT", 3)
    for _ in range(3):
        assert client.post("/api/auth/email/request", json={"email": "flood@example.com"}).status_code == 200
    r = client.post("/api/auth/email/request", json={"email": "Flood@Example.com"})  # same address, any case
    assert r.status_code == 429 and r.json["error"]["code"] == "too_many_requests"
    assert "10 minutes" in r.json["error"]["message"]
    # Another address is unaffected.
    assert client.post("/api/auth/email/request", json={"email": "other@example.com"}).status_code == 200
    # Spanish copy
    r = client.post("/api/auth/email/request", json={"email": "flood@example.com"}, headers={"Accept-Language": "es"})
    assert r.status_code == 429 and "demasiados códigos" in r.json["error"]["message"]


def test_latest_code_still_works_after_a_throttled_request(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_REQUEST_LIMIT", 1)
    code = client.post("/api/auth/email/request", json={"email": "one@example.com"}).json["dev_code"]
    assert client.post("/api/auth/email/request", json={"email": "one@example.com"}).status_code == 429
    r = client.post("/api/auth/email/verify", json={"email": "one@example.com", "code": code})
    assert r.status_code == 200 and "token" in r.json


def test_per_ip_code_requests_are_limited(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_IP_LIMIT", 2)
    assert client.post("/api/auth/email/request", json={"email": "a1@example.com"}).status_code == 200
    assert client.post("/api/auth/email/request", json={"email": "a2@example.com"}).status_code == 200
    r = client.post("/api/auth/email/request", json={"email": "a3@example.com"})
    assert r.status_code == 429 and r.json["error"]["code"] == "too_many_requests"
    # A different client address (the proxy-appended hop) is counted separately.
    r = client.post("/api/auth/email/request", json={"email": "a3@example.com"},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 200


def test_invalid_email_does_not_consume_the_ip_budget(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_IP_LIMIT", 1)
    assert client.post("/api/auth/email/request", json={"email": "nope"}).status_code == 422
    assert client.post("/api/auth/email/request", json={"email": "ok@example.com"}).status_code == 200


def test_review_login_uses_fixed_code_and_sends_nothing(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "REVIEW_LOGIN_EMAIL", "review@lendly.app")
    monkeypatch.setitem(app.config, "REVIEW_LOGIN_CODE", "24681357")
    monkeypatch.setitem(app.config, "DEV_RETURN_OTP", False)  # production-like: no code in the response
    # Mailgun is unconfigured in TestConfig, so a normal address would get a 503 here…
    assert client.post("/api/auth/email/request", json={"email": "normal@example.com"}).status_code == 503
    # …but the review address works regardless and never leaks the code.
    r = client.post("/api/auth/email/request", json={"email": "Review@Lendly.app"})
    assert r.status_code == 200 and r.json == {"sent": True}
    assert client.post("/api/auth/email/verify", json={"email": "review@lendly.app", "code": "00000000"}).status_code == 401
    r = client.post("/api/auth/email/verify", json={"email": "review@lendly.app", "code": "24681357"})
    assert r.status_code == 200 and r.json["user"]["email"] == "review@lendly.app"


def test_review_login_is_disabled_unless_both_values_are_set(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "REVIEW_LOGIN_EMAIL", "review@lendly.app")
    monkeypatch.setitem(app.config, "REVIEW_LOGIN_CODE", None)
    monkeypatch.setitem(app.config, "DEV_RETURN_OTP", False)
    assert client.post("/api/auth/email/request", json={"email": "review@lendly.app"}).status_code == 503


def test_gmail_aliases_share_one_inbox_budget(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "OTP_REQUEST_LIMIT", 1)
    assert client.post("/api/auth/email/request", json={"email": "victim@gmail.com"}).status_code == 200
    for alias in ("victim+1@gmail.com", "v.ictim@gmail.com", "Victim+promo@googlemail.com"):
        r = client.post("/api/auth/email/request", json={"email": alias})
        assert r.status_code == 429, (alias, r.status_code)
    # Non-Gmail: dots are significant but +tags are not.
    assert client.post("/api/auth/email/request", json={"email": "ana@example.com"}).status_code == 200
    assert client.post("/api/auth/email/request", json={"email": "ana+x@example.com"}).status_code == 429
    assert client.post("/api/auth/email/request", json={"email": "a.na@example.com"}).status_code == 200


def test_concurrent_code_requests_cannot_overshoot_the_limit(app, monkeypatch):
    import threading
    monkeypatch.setitem(app.config, "OTP_REQUEST_LIMIT", 1)
    results, barrier = [], threading.Barrier(8)

    def go():
        c = app.test_client()
        barrier.wait()
        results.append(c.post("/api/auth/email/request", json={"email": "burst@example.com"}).status_code)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sorted(results) == [200] + [429] * 7, results


def test_review_code_must_be_8_to_12_digits(monkeypatch):
    import importlib
    from app import config
    for bad in ("1234567", "1234567890123", "abcdefgh"):
        monkeypatch.setenv("REVIEW_LOGIN_EMAIL", "review@lendly.app")
        monkeypatch.setenv("REVIEW_LOGIN_CODE", bad)
        with pytest.raises(RuntimeError):
            importlib.reload(config)
    monkeypatch.setenv("REVIEW_LOGIN_CODE", "24681357")
    importlib.reload(config)
    monkeypatch.delenv("REVIEW_LOGIN_CODE"); monkeypatch.delenv("REVIEW_LOGIN_EMAIL")
    importlib.reload(config)
