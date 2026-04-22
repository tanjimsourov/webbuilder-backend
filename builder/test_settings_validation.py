import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase


REPO_ROOT = Path(__file__).resolve().parents[1]


def _base_production_env() -> dict[str, str]:
    env = os.environ.copy()
    scrub_prefixes = (
        "DJANGO_",
        "AWS_",
        "SENTRY_",
        "STRIPE_",
        "OPENAI_",
        "PAYLOAD_",
        "LIBRECRAWL_",
        "SERPBEAR_",
        "UMAMI_",
        "NAMECHEAP_",
        "NEXT_PUBLIC_",
    )
    for key in list(env.keys()):
        if key.startswith(scrub_prefixes):
            env.pop(key, None)

    env.update(
        {
            "DJANGO_DEBUG": "false",
            "APP_ENV": "production",
            "APP_PORT": "8000",
            "APP_URL": "https://api.example.com",
            "DATABASE_URL": "postgresql://webbuilder:super-strong-db-password-1234567890@127.0.0.1:5432/webbuilder",
            "REDIS_URL": "redis://127.0.0.1:6379/1",
            "JWT_ACCESS_SECRET": "jwt-access-secret-abcdefghijklmnopqrstuvwxyz123456",
            "JWT_REFRESH_SECRET": "jwt-refresh-secret-abcdefghijklmnopqrstuvwxyz123456",
            "SESSION_SECRET": "prod-secret-key-1234567890abcdefghijklmnopqrstuvwxyz",
            "CORS_ALLOWED_ORIGINS": "https://app.example.com",
            "STORAGE_DRIVER": "local",
            "STORAGE_BUCKET": "webbuilder-assets",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "smtp-user",
            "SMTP_PASS": "smtp-password-1234567890",
            "STRIPE_SECRET_KEY": "stripe-secret-key-production-test-value-abcdefghijklmnopqrstuvwxyz",
            "STRIPE_PUBLISHABLE_KEY": "stripe-publishable-key-production-test-value-abcdefghijklmnopqrstuvwxyz",
            "STRIPE_WEBHOOK_SECRET": "stripe-webhook-secret-production-test-value-abcdefghijklmnopqrstuvwxyz",
            "OPENAI_API_KEY": "openai-api-key-production-test-value-abcdefghijklmnopqrstuvwxyz",
            "SENTRY_DSN": "https://A1b2C3d4E5f6A7b8C9d0@o0.ingest.sentry.io/1",
            "DJANGO_SECRET_KEY": "prod-secret-key-1234567890abcdefghijklmnopqrstuvwxyz",
            "DJANGO_ALLOWED_HOSTS": "api.example.com",
            "DJANGO_CORS_ALLOWED_ORIGINS": "https://app.example.com",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.example.com",
            "DJANGO_PLATFORM_FRONTEND_ORIGINS": "https://app.example.com",
            "DJANGO_USE_X_FORWARDED_HOST": "true",
            "DJANGO_SESSION_COOKIE_SECURE": "true",
            "DJANGO_CSRF_COOKIE_SECURE": "true",
            "DJANGO_SECURE_SSL_REDIRECT": "true",
            "DJANGO_SECURE_HSTS_SECONDS": "31536000",
            "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS": "true",
            "DJANGO_SECURE_HSTS_PRELOAD": "true",
            "DJANGO_X_FRAME_OPTIONS": "DENY",
            "DJANGO_SESSION_COOKIE_SAMESITE": "Lax",
            "DJANGO_CSRF_COOKIE_SAMESITE": "Lax",
            "DJANGO_DB_ENGINE": "django.db.backends.postgresql",
            "DJANGO_DB_NAME": "webbuilder",
            "DJANGO_DB_USER": "webbuilder",
            "DJANGO_DB_PASSWORD": "super-strong-db-password-1234567890",
            "DJANGO_DB_HOST": "127.0.0.1",
            "DJANGO_DB_PORT": "5432",
            "DJANGO_CACHE_URL": "redis://127.0.0.1:6379/1",
            "DJANGO_METRICS_AUTH_TOKEN": "metrics-token-1234567890-production",
            "DJANGO_EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
            "LIBRECRAWL_ENABLED": "false",
            "SERPBEAR_ENABLED": "false",
            "UMAMI_ENABLED": "false",
            "PAYLOAD_CMS_ENABLED": "false",
            "PAYLOAD_ECOMMERCE_ENABLED": "false",
        }
    )
    return env


def _run_manage_check(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


class SettingsValidationTests(TestCase):
    def test_production_fails_without_secret_key(self):
        env = _base_production_env()
        env.pop("DJANGO_SECRET_KEY", None)
        env.pop("SESSION_SECRET", None)

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be set", result.stderr + result.stdout)

    def test_production_fails_with_wildcard_allowed_hosts(self):
        env = _base_production_env()
        env["DJANGO_ALLOWED_HOSTS"] = "*"

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot include wildcard hosts", result.stderr + result.stdout)

    def test_production_fails_without_cache_url(self):
        env = _base_production_env()
        env.pop("DJANGO_CACHE_URL", None)
        env.pop("REDIS_URL", None)

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required environment variables: REDIS_URL", result.stderr + result.stdout)

    def test_production_fails_when_metrics_query_token_is_enabled(self):
        env = _base_production_env()
        env["DJANGO_METRICS_ALLOW_QUERY_TOKEN"] = "true"

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_METRICS_ALLOW_QUERY_TOKEN must be false in production", result.stderr + result.stdout)

    def test_production_fails_when_magic_login_is_enabled(self):
        env = _base_production_env()
        env["DJANGO_AUTH_MAGIC_LOGIN_ENABLED"] = "true"

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_AUTH_MAGIC_LOGIN_ENABLED must be false in production", result.stderr + result.stdout)

    def test_production_check_passes_with_required_configuration(self):
        result = _run_manage_check(_base_production_env())

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
