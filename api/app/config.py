import os


def _normalize_db_url(url: str) -> str:
    # Render-style postgres:// URLs -> SQLAlchemy 2 + psycopg3 driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.getenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/lendly_dev")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv("SECRET_KEY", os.getenv("JWT_SECRET", "dev-secret"))
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
    JWT_TTL_DAYS = int(os.getenv("JWT_TTL_DAYS", "90"))
    APPLE_BUNDLE_ID = os.getenv("APPLE_BUNDLE_ID", "com.sotodev.lendly")
    DEV_RETURN_OTP = _truthy(os.getenv("DEV_RETURN_OTP"))
    OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "10"))
    INVITE_TTL_DAYS = int(os.getenv("INVITE_TTL_DAYS", "14"))
    INVITE_LINK_BASE = os.getenv("INVITE_LINK_BASE", "lendly://invite")
    # Email delivery (login codes). Same names as the emailer project.
    MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY")
    MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN")
    MAILGUN_FROM = os.getenv("MAILGUN_FROM")
    MAILGUN_BASE_URL = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net")
    # Login-code abuse limits: per e-mail address (counted in the DB) and per client IP
    # (in memory, so per gunicorn worker — a backstop, not an exact global limit).
    OTP_REQUEST_LIMIT = int(os.getenv("OTP_REQUEST_LIMIT", "3"))
    OTP_REQUEST_WINDOW_MINUTES = int(os.getenv("OTP_REQUEST_WINDOW_MINUTES", "10"))
    OTP_IP_LIMIT = int(os.getenv("OTP_IP_LIMIT", "20"))
    # App Review demo account: this address always receives this fixed code and nothing is
    # e-mailed, so Apple's reviewers can sign in. Both unset = disabled. Use 8+ digits.
    REVIEW_LOGIN_EMAIL = (os.getenv("REVIEW_LOGIN_EMAIL") or "").strip().lower() or None
    REVIEW_LOGIN_CODE = (os.getenv("REVIEW_LOGIN_CODE") or "").strip() or None
    if REVIEW_LOGIN_CODE is not None and not (REVIEW_LOGIN_CODE.isdigit() and 8 <= len(REVIEW_LOGIN_CODE) <= 12):
        # The verify route caps codes at 12 characters; shorter than 8 is brute-forceable.
        raise RuntimeError("REVIEW_LOGIN_CODE must be 8 to 12 digits")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/lendly_test")
    )
    JWT_SECRET = "test-secret"
    DEV_RETURN_OTP = True
    MAILGUN_API_KEY = None
    MAILGUN_DOMAIN = None
    MAILGUN_FROM = None
    OTP_REQUEST_LIMIT = 1000      # individual tests opt in to the real limit
    OTP_IP_LIMIT = 1_000_000
    REVIEW_LOGIN_EMAIL = None
    REVIEW_LOGIN_CODE = None
