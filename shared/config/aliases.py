from __future__ import annotations

import os
from dataclasses import dataclass
from typing import MutableMapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class DatabaseParts:
    engine: str
    name: str
    user: str
    password: str
    host: str
    port: str


def _set_if_missing(env: MutableMapping[str, str], key: str, value: str) -> None:
    if key in env and str(env.get(key) or "").strip():
        return
    if value is None:
        return
    env[key] = str(value)


def _parse_database_url(database_url: str) -> DatabaseParts | None:
    value = (database_url or "").strip()
    if not value:
        return None

    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()

    if scheme in {"postgres", "postgresql"}:
        engine = "django.db.backends.postgresql"
    elif scheme in {"sqlite", "sqlite3"}:
        engine = "django.db.backends.sqlite3"
    else:
        return None

    if engine.endswith("sqlite3"):
        # sqlite:///relative/path.db or sqlite:////abs/path.db
        name = parsed.path.lstrip("/") if parsed.path else ""
        return DatabaseParts(
            engine=engine,
            name=name or "db.sqlite3",
            user="",
            password="",
            host="",
            port="",
        )

    return DatabaseParts(
        engine=engine,
        name=(parsed.path or "").lstrip("/"),
        user=parsed.username or "",
        password=parsed.password or "",
        host=parsed.hostname or "",
        port=str(parsed.port or ""),
    )


def apply_env_aliases(env: MutableMapping[str, str] | None = None) -> None:
    """Apply compatibility aliases across env var naming conventions.

    This repo historically uses `DJANGO_*` variables. Newer deployments may
    prefer generic `APP_*`/`DATABASE_URL`/`REDIS_URL`-style variables. This
    function maps the generic names into the canonical `DJANGO_*`/service
    variables if they are not already set.
    """

    env = env or os.environ

    # --- App/runtime aliases -------------------------------------------------
    app_env = (env.get("APP_ENV") or "").strip().lower()
    if app_env and "DJANGO_DEBUG" not in env:
        _set_if_missing(env, "DJANGO_DEBUG", "false" if app_env in {"prod", "production"} else "true")

    _set_if_missing(env, "DJANGO_SECRET_KEY", env.get("SESSION_SECRET") or "")
    _set_if_missing(env, "DJANGO_CORS_ALLOWED_ORIGINS", env.get("CORS_ALLOWED_ORIGINS") or "")

    # --- Database aliases ----------------------------------------------------
    db_url = (env.get("DATABASE_URL") or "").strip()
    if db_url and not str(env.get("DJANGO_DB_ENGINE") or "").strip():
        parts = _parse_database_url(db_url)
        if parts:
            _set_if_missing(env, "DJANGO_DB_ENGINE", parts.engine)
            _set_if_missing(env, "DJANGO_DB_NAME", parts.name)
            _set_if_missing(env, "DJANGO_DB_USER", parts.user)
            _set_if_missing(env, "DJANGO_DB_PASSWORD", parts.password)
            _set_if_missing(env, "DJANGO_DB_HOST", parts.host)
            _set_if_missing(env, "DJANGO_DB_PORT", parts.port)

    # --- Redis/cache aliases -------------------------------------------------
    redis_url = (env.get("REDIS_URL") or "").strip()
    if redis_url:
        _set_if_missing(env, "DJANGO_CACHE_URL", redis_url)
        _set_if_missing(env, "CELERY_BROKER_URL", redis_url)
        _set_if_missing(env, "CELERY_RESULT_BACKEND", redis_url)

    # --- Storage aliases -----------------------------------------------------
    storage_driver = (env.get("STORAGE_DRIVER") or "").strip().lower()
    if storage_driver:
        if storage_driver in {"s3", "minio"}:
            _set_if_missing(env, "DJANGO_USE_S3_STORAGE", "true")
        elif storage_driver in {"local", "filesystem", "fs"}:
            _set_if_missing(env, "DJANGO_USE_S3_STORAGE", "false")

    _set_if_missing(env, "AWS_STORAGE_BUCKET_NAME", env.get("STORAGE_BUCKET") or "")

    # --- SMTP aliases --------------------------------------------------------
    _set_if_missing(env, "DJANGO_EMAIL_HOST", env.get("SMTP_HOST") or "")
    _set_if_missing(env, "DJANGO_EMAIL_PORT", env.get("SMTP_PORT") or "")
    _set_if_missing(env, "DJANGO_EMAIL_HOST_USER", env.get("SMTP_USER") or "")
    _set_if_missing(env, "DJANGO_EMAIL_HOST_PASSWORD", env.get("SMTP_PASS") or "")

