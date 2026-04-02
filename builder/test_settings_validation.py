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
            "SENTRY_DSN": "",
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

        result = _run_manage_check(env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_CACHE_URL must be set in production", result.stderr + result.stdout)

    def test_production_check_passes_with_required_configuration(self):
        result = _run_manage_check(_base_production_env())

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
