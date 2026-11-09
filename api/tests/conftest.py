import pytest
from sqlalchemy import text

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(autouse=True)
def clean_tables(app):
    yield
    _db.session.rollback()
    _db.session.remove()
    tables = ", ".join(t.name for t in reversed(_db.metadata.sorted_tables))
    _db.session.execute(text(f"TRUNCATE {tables} CASCADE"))
    _db.session.commit()


@pytest.fixture
def client(app):
    return app.test_client()


class Api:
    """Tiny helper: signs in via email code and keeps the bearer token."""

    def __init__(self, client, email):
        self.client = client
        self.email = email
        r = client.post("/api/auth/email/request", json={"email": email})
        assert r.status_code == 200, r.json
        r = client.post("/api/auth/email/verify", json={"email": email, "code": r.json["dev_code"]})
        assert r.status_code == 200, r.json
        self.token = r.json["token"]
        self.user = r.json["user"]
        self.tenant_id = None

    def headers(self):
        h = {"Authorization": f"Bearer {self.token}"}
        if self.tenant_id:
            h["X-Tenant-Id"] = self.tenant_id
        return h

    def create_tenant(self, name="Soto Lending"):
        r = self.client.post("/api/tenants", json={"name": name}, headers=self.headers())
        assert r.status_code == 201, r.json
        self.tenant_id = r.json["tenant"]["id"]
        return r.json

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers(), **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(path, json=json, headers=self.headers(), **kw)

    def patch(self, path, json=None, **kw):
        return self.client.patch(path, json=json, headers=self.headers(), **kw)

    def delete(self, path, **kw):
        return self.client.delete(path, headers=self.headers(), **kw)


@pytest.fixture
def api(client):
    return lambda email: Api(client, email)


@pytest.fixture
def admin(api):
    a = api("lender@example.com")
    a.create_tenant()
    return a
