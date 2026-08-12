import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parent.parent


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "change-this-secret-before-deploy"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 16777216))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or str(BASE_DIR / "uploads")
    GENERATED_FOLDER = os.environ.get("GENERATED_FOLDER") or str(BASE_DIR / "generated")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    RATE_LIMIT_ENABLED = _as_bool(os.environ.get("RATE_LIMIT_ENABLED"), False)
    REGISTRATION_OPEN = _as_bool(os.environ.get("REGISTRATION_OPEN"), False)
    MAIL_SERVER = os.environ.get("MAIL_SERVER") or ""
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME") or ""
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD") or ""
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or "noreply@crimegpt.local"
    MAIL_USE_TLS = _as_bool(os.environ.get("MAIL_USE_TLS"), True)
    MAIL_USE_SSL = _as_bool(os.environ.get("MAIL_USE_SSL"), False)
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or ""
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    GEMINI_LOG_PROMPTS = os.environ.get("GEMINI_LOG_PROMPTS", "0") == "1"
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or "memory://"
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or "cache+memory://"
    SEED_SUPERADMIN_IDENTIFIER = os.environ.get("SEED_SUPERADMIN_IDENTIFIER") or "superadmin"
    SEED_SUPERADMIN_PASSWORD = os.environ.get("SEED_SUPERADMIN_PASSWORD") or "CrimeGPT!Admin2026"
    CACHE_TYPE = "RedisCache" if (os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL") or "").startswith("redis://") else "SimpleCache"
    CACHE_REDIS_URL = os.environ.get("REDIS_URL") or os.environ.get("CELERY_BROKER_URL") or ""
    CACHE_DEFAULT_TIMEOUT = 300
    RATELIMIT_STORAGE_URI = "memory://"
    RATELIMIT_HEADERS_ENABLED = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_DURATION = timedelta(days=7)


class DevelopmentConfig(Config):
    DEBUG = True
    ENV_NAME = "development"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or (
        "sqlite:///" + str(BASE_DIR / "instance" / "app.db")
    )
    RATE_LIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    REGISTRATION_OPEN = True
    WTF_CSRF_ENABLED = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    ENV_NAME = "testing"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    WTF_CSRF_ENABLED = False
    RATE_LIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SEED_SUPERADMIN_IDENTIFIER = "superadmin"
    SEED_SUPERADMIN_PASSWORD = "CrimeGPT!Admin2026"
    REGISTRATION_OPEN = True


class ProductionConfig(Config):
    DEBUG = False
    ENV_NAME = "production"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    RATE_LIMIT_ENABLED = True
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    WTF_CSRF_ENABLED = True


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
}


def get_config(name=None):
    key = (name or os.environ.get("FLASK_ENV") or "development").strip().lower()
    cfg = CONFIG_MAP.get(key, DevelopmentConfig)
    if cfg is ProductionConfig and not os.environ.get("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required in production")
    return cfg
