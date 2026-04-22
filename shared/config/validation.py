from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RequiredEnv:
    name: str
    description: str


REQUIRED_ENV_VARS: tuple[RequiredEnv, ...] = (
    RequiredEnv("APP_ENV", "Deployment environment (development/staging/production)."),
    RequiredEnv("APP_PORT", "HTTP listen port."),
    RequiredEnv("APP_URL", "Public base URL (https://...)."),
    RequiredEnv("DATABASE_URL", "Database connection URL."),
    RequiredEnv("REDIS_URL", "Redis connection URL."),
    RequiredEnv("JWT_ACCESS_SECRET", "JWT access token signing secret."),
    RequiredEnv("JWT_REFRESH_SECRET", "JWT refresh token signing secret."),
    RequiredEnv("SESSION_SECRET", "Session signing/crypto secret."),
    RequiredEnv("CORS_ALLOWED_ORIGINS", "Comma-separated list of allowed origins."),
    RequiredEnv("STORAGE_DRIVER", "Storage backend driver (local|s3|minio)."),
    RequiredEnv("STORAGE_BUCKET", "Storage bucket name."),
    RequiredEnv("SMTP_HOST", "SMTP host."),
    RequiredEnv("SMTP_PORT", "SMTP port."),
    RequiredEnv("SMTP_USER", "SMTP username."),
    RequiredEnv("SMTP_PASS", "SMTP password."),
    RequiredEnv("STRIPE_SECRET_KEY", "Stripe secret key."),
    RequiredEnv("STRIPE_WEBHOOK_SECRET", "Stripe webhook signing secret."),
    RequiredEnv("SENTRY_DSN", "Sentry DSN."),
)


def environment_is_production(env: dict[str, str] | None = None) -> bool:
    env = env or os.environ
    app_env = (env.get("APP_ENV") or "").strip().lower()
    if app_env:
        return app_env in {"prod", "production"}
    return str(env.get("DJANGO_DEBUG") or "").strip().lower() in {"0", "false", "no", "off"}


def missing_required_env(env: dict[str, str] | None = None) -> list[str]:
    env = env or os.environ
    missing: list[str] = []
    for required in REQUIRED_ENV_VARS:
        value = str(env.get(required.name) or "").strip()
        if not value:
            missing.append(required.name)
    ai_candidates = (
        str(env.get("OPENAI_API_KEY") or "").strip(),
        str(env.get("AI_PROVIDER_API_KEY") or "").strip(),
        str(env.get("ANTHROPIC_API_KEY") or "").strip(),
        str(env.get("GOOGLE_AI_API_KEY") or "").strip(),
    )
    if not any(ai_candidates):
        missing.append("OPENAI_API_KEY_OR_PROVIDER_AI_KEY")
    return missing
