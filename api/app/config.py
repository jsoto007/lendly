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


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5432/lendly_test")
    )
    JWT_SECRET = "test-secret"
    DEV_RETURN_OTP = True
