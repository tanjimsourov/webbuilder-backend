import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
DEPS_DIR = BASE_DIR / ".deps"
if DEPS_DIR.exists():
    sys.path.insert(0, str(DEPS_DIR))

MIRROR_IMPORT_ROOT = Path(os.environ.get("MIRROR_IMPORT_ROOT", BASE_DIR / ".mirror-imports")).expanduser()


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def env_str(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def env_octal(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value, 8)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an octal value like 640 or 750.") from exc


def _normalize_origin(value: str) -> str:
    return value.rstrip("/") if value else value


def _merge_origins(*origin_lists: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for origins in origin_lists:
        for origin in origins:
            normalized = _normalize_origin(origin)
            if not normalized or normalized in seen:
                continue
            merged.append(normalized)
            seen.add(normalized)
    return merged


RUNNING_TESTS = any(arg.startswith("test") for arg in sys.argv[1:])
USE_SQLITE_FOR_TESTS = env_bool("DJANGO_USE_SQLITE_FOR_TESTS", True)

if RUNNING_TESTS and USE_SQLITE_FOR_TESTS:
    os.environ["DJANGO_DB_ENGINE"] = "django.db.backends.sqlite3"
    os.environ["DJANGO_DB_NAME"] = str(BASE_DIR / "test_db.sqlite3")
    os.environ["DJANGO_DB_USER"] = ""
    os.environ["DJANGO_DB_PASSWORD"] = ""
    os.environ["DJANGO_DB_HOST"] = ""
    os.environ["DJANGO_DB_PORT"] = ""


DEBUG = env_bool("DJANGO_DEBUG", RUNNING_TESTS)
IS_PRODUCTION = not DEBUG and not RUNNING_TESTS


def _looks_like_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    markers = (
        "replace",
        "change-me",
        "changeme",
        "example",
        "generate",
        "placeholder",
        "django-insecure",
    )
    return any(marker in lowered for marker in markers)


def _ensure_secret(name: str, *, minimum_length: int = 32) -> str:
    value = env_str(name)
    if not value:
        raise ImproperlyConfigured(f"{name} must be set.")
    if len(value) < minimum_length:
        raise ImproperlyConfigured(f"{name} must be at least {minimum_length} characters.")
    if not RUNNING_TESTS and _looks_like_placeholder_secret(value):
        raise ImproperlyConfigured(f"{name} appears to be a placeholder; set a real secret.")
    return value


def _is_local_hostname(hostname: str) -> bool:
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True
    if hostname.startswith("127."):
        return True
    return False


def _validate_origin_list(name: str, origins: list[str], *, allow_http_localhost: bool = False) -> None:
    for origin in origins:
        lowered = origin.strip().lower()
        if not lowered:
            continue
        if lowered == "*" or "*" in lowered:
            raise ImproperlyConfigured(f"{name} cannot contain wildcard origins.")
        parsed = urlparse(lowered)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ImproperlyConfigured(f"{name} contains invalid origin: {origin}")
        if parsed.fragment or parsed.query or parsed.params:
            raise ImproperlyConfigured(f"{name} origin must not include path/query/fragment: {origin}")
        if parsed.username or parsed.password:
            raise ImproperlyConfigured(f"{name} origin must not include credentials: {origin}")
        hostname = (parsed.hostname or "").strip()
        if not allow_http_localhost and parsed.scheme != "https":
            raise ImproperlyConfigured(f"{name} must use https origins in production: {origin}")
        if allow_http_localhost and parsed.scheme == "http" and not _is_local_hostname(hostname):
            raise ImproperlyConfigured(f"{name} only allows http origins for localhost in development: {origin}")


def _validate_allowed_hosts(hosts: list[str]) -> None:
    for host in hosts:
        value = host.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered == "*" or "*" in lowered or lowered.startswith("."):
            raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS cannot include wildcard hosts.")
        if "://" in lowered:
            raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS entries must be hostnames, not URLs.")
        if "/" in lowered:
            raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS entries must not include paths.")
        if ":" in lowered and not lowered.startswith("["):
            raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS entries must not include ports.")


def _validate_samesite(name: str, value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"lax", "strict", "none"}:
        raise ImproperlyConfigured(f"{name} must be one of Lax, Strict, or None.")
    return normalized


def _ensure_not_placeholder(name: str, value: str) -> None:
    if value and IS_PRODUCTION and _looks_like_placeholder_secret(value):
        raise ImproperlyConfigured(f"{name} appears to be a placeholder.")


if RUNNING_TESTS:
    os.environ.setdefault(
        "DJANGO_SECRET_KEY",
        "test-only-secret-key-not-for-production-1234567890",
    )

SECRET_KEY = _ensure_secret("DJANGO_SECRET_KEY", minimum_length=32)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"] if DEBUG else [])
if IS_PRODUCTION and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be configured when DJANGO_DEBUG is false.")
_validate_allowed_hosts(ALLOWED_HOSTS)

LIBRECRAWL_ENABLED = env_bool("LIBRECRAWL_ENABLED", False)
LIBRECRAWL_HOST = env_str("LIBRECRAWL_HOST", "127.0.0.1")
LIBRECRAWL_PORT = int(env_str("LIBRECRAWL_PORT", "5055"))
LIBRECRAWL_PUBLIC_URL = env_str(
    "LIBRECRAWL_PUBLIC_URL",
    f"http://127.0.0.1:{LIBRECRAWL_PORT}" if DEBUG else "",
)
LIBRECRAWL_LOCAL_MODE = env_bool("LIBRECRAWL_LOCAL_MODE", DEBUG)
LIBRECRAWL_SECRET_KEY = env_str("LIBRECRAWL_SECRET_KEY")
if LIBRECRAWL_ENABLED and not LIBRECRAWL_LOCAL_MODE and not LIBRECRAWL_SECRET_KEY:
    raise ImproperlyConfigured(
        "LIBRECRAWL_SECRET_KEY must be set when LIBRECRAWL_ENABLED=true and LIBRECRAWL_LOCAL_MODE=false."
    )
_ensure_not_placeholder("LIBRECRAWL_SECRET_KEY", LIBRECRAWL_SECRET_KEY)

SERPBEAR_ENABLED = env_bool("SERPBEAR_ENABLED", False)
SERPBEAR_HOST = env_str("SERPBEAR_HOST", "127.0.0.1")
SERPBEAR_PORT = int(env_str("SERPBEAR_PORT", "5060"))
SERPBEAR_PUBLIC_URL = env_str(
    "SERPBEAR_PUBLIC_URL",
    f"http://127.0.0.1:{SERPBEAR_PORT}" if DEBUG else "",
)

UMAMI_ENABLED = env_bool("UMAMI_ENABLED", False)
UMAMI_HOST = env_str("UMAMI_HOST", "127.0.0.1")
UMAMI_PORT = int(env_str("UMAMI_PORT", "5070"))
UMAMI_PUBLIC_URL = env_str(
    "UMAMI_PUBLIC_URL",
    f"http://127.0.0.1:{UMAMI_PORT}" if DEBUG else "",
)

PAYLOAD_CMS_ENABLED = env_bool("PAYLOAD_CMS_ENABLED", False)
PAYLOAD_CMS_HOST = env_str("PAYLOAD_CMS_HOST", "127.0.0.1")
PAYLOAD_CMS_PORT = int(env_str("PAYLOAD_CMS_PORT", "5080"))
PAYLOAD_CMS_PUBLIC_URL = env_str(
    "PAYLOAD_CMS_PUBLIC_URL",
    f"http://127.0.0.1:{PAYLOAD_CMS_PORT}" if DEBUG else "",
)
PAYLOAD_CMS_DATABASE_URL = env_str("PAYLOAD_CMS_DATABASE_URL")
PAYLOAD_CMS_SECRET = env_str("PAYLOAD_CMS_SECRET")
PAYLOAD_CMS_PREVIEW_SECRET = env_str("PAYLOAD_CMS_PREVIEW_SECRET", PAYLOAD_CMS_SECRET)
PAYLOAD_CMS_CRON_SECRET = env_str("PAYLOAD_CMS_CRON_SECRET", PAYLOAD_CMS_SECRET)
if PAYLOAD_CMS_ENABLED:
    if not PAYLOAD_CMS_DATABASE_URL:
        raise ImproperlyConfigured("PAYLOAD_CMS_DATABASE_URL must be set when PAYLOAD_CMS_ENABLED=true.")
    if not PAYLOAD_CMS_SECRET:
        raise ImproperlyConfigured("PAYLOAD_CMS_SECRET must be set when PAYLOAD_CMS_ENABLED=true.")
_ensure_not_placeholder("PAYLOAD_CMS_SECRET", PAYLOAD_CMS_SECRET)
_ensure_not_placeholder("PAYLOAD_CMS_PREVIEW_SECRET", PAYLOAD_CMS_PREVIEW_SECRET)
_ensure_not_placeholder("PAYLOAD_CMS_CRON_SECRET", PAYLOAD_CMS_CRON_SECRET)

PAYLOAD_ECOMMERCE_ENABLED = env_bool("PAYLOAD_ECOMMERCE_ENABLED", False)
PAYLOAD_ECOMMERCE_HOST = env_str("PAYLOAD_ECOMMERCE_HOST", "127.0.0.1")
PAYLOAD_ECOMMERCE_PORT = int(env_str("PAYLOAD_ECOMMERCE_PORT", "5085"))
PAYLOAD_ECOMMERCE_PUBLIC_URL = env_str(
    "PAYLOAD_ECOMMERCE_PUBLIC_URL",
    f"http://127.0.0.1:{PAYLOAD_ECOMMERCE_PORT}" if DEBUG else "",
)
PAYLOAD_ECOMMERCE_DATABASE_URL = env_str("PAYLOAD_ECOMMERCE_DATABASE_URL")
PAYLOAD_ECOMMERCE_SECRET = env_str("PAYLOAD_ECOMMERCE_SECRET")
PAYLOAD_ECOMMERCE_PREVIEW_SECRET = env_str("PAYLOAD_ECOMMERCE_PREVIEW_SECRET", PAYLOAD_ECOMMERCE_SECRET)
PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY = env_str("PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY")
PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY = env_str("PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY")
PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET = env_str("PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET")
if PAYLOAD_ECOMMERCE_ENABLED:
    if not PAYLOAD_ECOMMERCE_DATABASE_URL:
        raise ImproperlyConfigured(
            "PAYLOAD_ECOMMERCE_DATABASE_URL must be set when PAYLOAD_ECOMMERCE_ENABLED=true."
        )
    if not PAYLOAD_ECOMMERCE_SECRET:
        raise ImproperlyConfigured("PAYLOAD_ECOMMERCE_SECRET must be set when PAYLOAD_ECOMMERCE_ENABLED=true.")
    if not (
        PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY
        and PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY
        and PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET
    ):
        raise ImproperlyConfigured(
            "PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY, PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY, and "
            "PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET must be set when PAYLOAD_ECOMMERCE_ENABLED=true."
        )
_ensure_not_placeholder("PAYLOAD_ECOMMERCE_SECRET", PAYLOAD_ECOMMERCE_SECRET)
_ensure_not_placeholder("PAYLOAD_ECOMMERCE_PREVIEW_SECRET", PAYLOAD_ECOMMERCE_PREVIEW_SECRET)
_ensure_not_placeholder("PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY", PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY)
_ensure_not_placeholder(
    "PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY", PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY
)
_ensure_not_placeholder("PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET", PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET)

STRIPE_SECRET_KEY = env_str("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = env_str("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = env_str("STRIPE_WEBHOOK_SECRET")
if IS_PRODUCTION and any([STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET]) and not all(
    [STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET]
):
    raise ImproperlyConfigured(
        "STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, and STRIPE_WEBHOOK_SECRET must all be set together."
    )
_ensure_not_placeholder("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY)
_ensure_not_placeholder("STRIPE_PUBLISHABLE_KEY", STRIPE_PUBLISHABLE_KEY)
_ensure_not_placeholder("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)

OPENAI_API_KEY = env_str("OPENAI_API_KEY")
OPENAI_MODEL = env_str("OPENAI_MODEL", "gpt-4o-mini")
_ensure_not_placeholder("OPENAI_API_KEY", OPENAI_API_KEY)

NEXTJS_SITE_RUNTIME_BASE_URL = env_str("NEXTJS_SITE_RUNTIME_BASE_URL")
NEXTJS_REVALIDATE_SECRET = env_str("NEXTJS_REVALIDATE_SECRET")
NEXTJS_REVALIDATE_ENDPOINT = env_str("NEXTJS_REVALIDATE_ENDPOINT", "/api/revalidate")
NEXTJS_REVALIDATE_TIMEOUT_SECONDS = int(env_str("NEXTJS_REVALIDATE_TIMEOUT_SECONDS", "10"))
if NEXTJS_SITE_RUNTIME_BASE_URL:
    _validate_origin_list(
        "NEXTJS_SITE_RUNTIME_BASE_URL",
        [NEXTJS_SITE_RUNTIME_BASE_URL],
        allow_http_localhost=DEBUG,
    )
if IS_PRODUCTION and NEXTJS_SITE_RUNTIME_BASE_URL and not NEXTJS_REVALIDATE_SECRET:
    raise ImproperlyConfigured(
        "NEXTJS_REVALIDATE_SECRET must be set when NEXTJS_SITE_RUNTIME_BASE_URL is configured in production."
    )
_ensure_not_placeholder("NEXTJS_REVALIDATE_SECRET", NEXTJS_REVALIDATE_SECRET)

NAMECHEAP_API_USER = env_str("NAMECHEAP_API_USER")
NAMECHEAP_API_KEY = env_str("NAMECHEAP_API_KEY")
NAMECHEAP_USERNAME = env_str("NAMECHEAP_USERNAME")
NAMECHEAP_CLIENT_IP = env_str("NAMECHEAP_CLIENT_IP")
_ensure_not_placeholder("NAMECHEAP_API_USER", NAMECHEAP_API_USER)
_ensure_not_placeholder("NAMECHEAP_API_KEY", NAMECHEAP_API_KEY)

for _service_env_name, _service_public_url in [
    ("LIBRECRAWL_PUBLIC_URL", LIBRECRAWL_PUBLIC_URL),
    ("SERPBEAR_PUBLIC_URL", SERPBEAR_PUBLIC_URL),
    ("UMAMI_PUBLIC_URL", UMAMI_PUBLIC_URL),
    ("PAYLOAD_CMS_PUBLIC_URL", PAYLOAD_CMS_PUBLIC_URL),
    ("PAYLOAD_ECOMMERCE_PUBLIC_URL", PAYLOAD_ECOMMERCE_PUBLIC_URL),
    ("NEXTJS_SITE_RUNTIME_BASE_URL", NEXTJS_SITE_RUNTIME_BASE_URL),
]:
    if _service_public_url:
        _validate_origin_list(
            _service_env_name,
            [_service_public_url],
            allow_http_localhost=DEBUG,
        )

ENABLE_REQUEST_SEED_DATA = env_bool("DJANGO_ENABLE_REQUEST_SEED_DATA", DEBUG)
AUTH_BOOTSTRAP_ENABLED = env_bool("DJANGO_AUTH_BOOTSTRAP_ENABLED", DEBUG)
AUTH_BOOTSTRAP_TOKEN = env_str("DJANGO_AUTH_BOOTSTRAP_TOKEN")
AUTH_MAGIC_LOGIN_ENABLED = env_bool("DJANGO_AUTH_MAGIC_LOGIN_ENABLED", DEBUG)
METRICS_AUTH_TOKEN = env_str("DJANGO_METRICS_AUTH_TOKEN")
_ensure_not_placeholder("DJANGO_AUTH_BOOTSTRAP_TOKEN", AUTH_BOOTSTRAP_TOKEN)
_ensure_not_placeholder("DJANGO_METRICS_AUTH_TOKEN", METRICS_AUTH_TOKEN)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "corsheaders",
    "rest_framework",
    # Project apps
    "core",
    "cms",
    "commerce",
    "forms",
    "blog",
    "analytics",
    "notifications",
    "jobs",
    "email_hosting",
    # Payments and billing
    "payments",
    # Domain provisioning
    "domains",
    # Legacy monolith (temporary)
    "builder",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "builder.middleware.RedirectMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "builder" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": env_str("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": env_str("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": env_str("DJANGO_DB_USER"),
        "PASSWORD": env_str("DJANGO_DB_PASSWORD"),
        "HOST": env_str("DJANGO_DB_HOST"),
        "PORT": env_str("DJANGO_DB_PORT"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ] if DEBUG else [],
)
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ] if DEBUG else [],
)

PLATFORM_FRONTEND_ORIGINS = env_list(
    "DJANGO_PLATFORM_FRONTEND_ORIGINS",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ] if DEBUG else [],
)

NEXT_PUBLIC_APP_ORIGIN = _normalize_origin(os.environ.get("NEXT_PUBLIC_APP_ORIGIN", ""))
if NEXT_PUBLIC_APP_ORIGIN:
    PLATFORM_FRONTEND_ORIGINS.append(NEXT_PUBLIC_APP_ORIGIN)

CORS_ALLOWED_ORIGINS = _merge_origins(CORS_ALLOWED_ORIGINS, PLATFORM_FRONTEND_ORIGINS)
CSRF_TRUSTED_ORIGINS = _merge_origins(CSRF_TRUSTED_ORIGINS, PLATFORM_FRONTEND_ORIGINS)
_validate_origin_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    CORS_ALLOWED_ORIGINS,
    allow_http_localhost=DEBUG,
)
_validate_origin_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    CSRF_TRUSTED_ORIGINS,
    allow_http_localhost=DEBUG,
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("DJANGO_THROTTLE_ANON", "100/hour"),
        "user": os.environ.get("DJANGO_THROTTLE_USER", "1000/hour"),
        "burst": os.environ.get("DJANGO_THROTTLE_BURST", "60/minute"),
        "auth_login": os.environ.get("DJANGO_THROTTLE_AUTH_LOGIN", "20/minute"),
        "auth_bootstrap": os.environ.get("DJANGO_THROTTLE_AUTH_BOOTSTRAP", "10/hour"),
        "auth_magic_login": os.environ.get("DJANGO_THROTTLE_AUTH_MAGIC_LOGIN", "10/minute"),
        "invitation_accept": os.environ.get("DJANGO_THROTTLE_INVITATION_ACCEPT", "30/hour"),
        "public_form": os.environ.get("DJANGO_THROTTLE_PUBLIC_FORM", "30/hour"),
        "public_comment": os.environ.get("DJANGO_THROTTLE_PUBLIC_COMMENT", "20/hour"),
        "public_checkout": os.environ.get("DJANGO_THROTTLE_PUBLIC_CHECKOUT", "60/hour"),
        "webhook": os.environ.get("DJANGO_THROTTLE_WEBHOOK", "1000/minute"),
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = env_bool("DJANGO_USE_X_FORWARDED_HOST", not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = env_str("DJANGO_SECURE_REFERRER_POLICY", "strict-origin-when-cross-origin")
SECURE_CROSS_ORIGIN_OPENER_POLICY = env_str("DJANGO_SECURE_CROSS_ORIGIN_OPENER_POLICY", "same-origin")
X_FRAME_OPTIONS = env_str("DJANGO_X_FRAME_OPTIONS", "SAMEORIGIN" if DEBUG else "DENY").upper()
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
DEFAULT_SAMESITE_POLICY = "Lax"
SESSION_COOKIE_SAMESITE = env_str("DJANGO_SESSION_COOKIE_SAMESITE", DEFAULT_SAMESITE_POLICY)
CSRF_COOKIE_SAMESITE = env_str("DJANGO_CSRF_COOKIE_SAMESITE", DEFAULT_SAMESITE_POLICY)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_AGE = int(env_str("DJANGO_SESSION_COOKIE_AGE", "1209600"))
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE", False)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False if DEBUG else True)
SECURE_HSTS_SECONDS = int(env_str("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", not DEBUG)
SECURE_REDIRECT_EXEMPT = env_list("DJANGO_SECURE_REDIRECT_EXEMPT", [])

_session_samesite = _validate_samesite("DJANGO_SESSION_COOKIE_SAMESITE", SESSION_COOKIE_SAMESITE)
_csrf_samesite = _validate_samesite("DJANGO_CSRF_COOKIE_SAMESITE", CSRF_COOKIE_SAMESITE)

if _session_samesite == "none" and not SESSION_COOKIE_SECURE:
    raise ImproperlyConfigured("SESSION_COOKIE_SECURE must be true when SESSION_COOKIE_SAMESITE=None.")
if _csrf_samesite == "none" and not CSRF_COOKIE_SECURE:
    raise ImproperlyConfigured("CSRF_COOKIE_SECURE must be true when CSRF_COOKIE_SAMESITE=None.")

if RUNNING_TESTS:
    SECURE_SSL_REDIRECT = False

# ---------------------------------------------------------------------------
# Email Configuration
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env_str(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env_str("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(env_str("DJANGO_EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False)
EMAIL_HOST_USER = env_str("DJANGO_EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env_str("DJANGO_EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = env_str("DJANGO_DEFAULT_FROM_EMAIL", "noreply@smcwebbuilder.com")
SERVER_EMAIL = env_str("DJANGO_SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# ---------------------------------------------------------------------------
# Email Hosting Provider Configuration
# ---------------------------------------------------------------------------
EMAIL_HOSTING_PROVIDER = env_str("EMAIL_HOSTING_PROVIDER", "local").lower()
EMAIL_HOSTING_API_BASE_URL = env_str("EMAIL_HOSTING_API_BASE_URL")
EMAIL_HOSTING_API_TOKEN = env_str("EMAIL_HOSTING_API_TOKEN")
EMAIL_HOSTING_API_TIMEOUT = int(env_str("EMAIL_HOSTING_API_TIMEOUT", "20"))
EMAIL_HOSTING_DNS_TIMEOUT = int(env_str("EMAIL_HOSTING_DNS_TIMEOUT", "8"))
EMAIL_HOSTING_DKIM_SELECTOR = env_str("EMAIL_HOSTING_DKIM_SELECTOR", "k1")
EMAIL_HOSTING_DKIM_PUBLIC_KEY = env_str("EMAIL_HOSTING_DKIM_PUBLIC_KEY")
EMAIL_HOSTING_MX_HOST = env_str("EMAIL_HOSTING_MX_HOST", "mail.{domain}")
EMAIL_HOSTING_SPF_TEMPLATE = env_str("EMAIL_HOSTING_SPF_TEMPLATE", "v=spf1 mx include:{domain} ~all")
EMAIL_HOSTING_DMARC_TEMPLATE = env_str(
    "EMAIL_HOSTING_DMARC_TEMPLATE",
    "v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}",
)
EMAIL_HOSTING_REQUIRE_ACTIVE_DOMAIN = env_bool("EMAIL_HOSTING_REQUIRE_ACTIVE_DOMAIN", True)

if EMAIL_HOSTING_PROVIDER not in {"local", "api"}:
    raise ImproperlyConfigured("EMAIL_HOSTING_PROVIDER must be either 'local' or 'api'.")
if EMAIL_HOSTING_PROVIDER == "api":
    if not EMAIL_HOSTING_API_BASE_URL:
        raise ImproperlyConfigured("EMAIL_HOSTING_API_BASE_URL must be set when EMAIL_HOSTING_PROVIDER=api.")
    if not EMAIL_HOSTING_API_TOKEN:
        raise ImproperlyConfigured("EMAIL_HOSTING_API_TOKEN must be set when EMAIL_HOSTING_PROVIDER=api.")
    _ensure_not_placeholder("EMAIL_HOSTING_API_TOKEN", EMAIL_HOSTING_API_TOKEN)

# ---------------------------------------------------------------------------
# Production Media Storage (S3-compatible)
# ---------------------------------------------------------------------------
USE_S3_STORAGE = env_bool("DJANGO_USE_S3_STORAGE", False)
AWS_STORAGE_BUCKET_NAME = env_str("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = env_str("AWS_S3_REGION_NAME", "us-east-1")
AWS_ACCESS_KEY_ID = env_str("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env_str("AWS_SECRET_ACCESS_KEY")
AWS_S3_ENDPOINT_URL = env_str("AWS_S3_ENDPOINT_URL")
AWS_S3_CUSTOM_DOMAIN = env_str("AWS_S3_CUSTOM_DOMAIN")

if USE_S3_STORAGE:
    if not AWS_STORAGE_BUCKET_NAME:
        raise ImproperlyConfigured("AWS_STORAGE_BUCKET_NAME must be set when DJANGO_USE_S3_STORAGE=true.")
    _ensure_not_placeholder("AWS_ACCESS_KEY_ID", AWS_ACCESS_KEY_ID)
    _ensure_not_placeholder("AWS_SECRET_ACCESS_KEY", AWS_SECRET_ACCESS_KEY)
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "region_name": AWS_S3_REGION_NAME,
                "access_key": AWS_ACCESS_KEY_ID,
                "secret_key": AWS_SECRET_ACCESS_KEY,
                "endpoint_url": AWS_S3_ENDPOINT_URL or None,
                "custom_domain": AWS_S3_CUSTOM_DOMAIN or None,
                "file_overwrite": False,
                "default_acl": env_str("AWS_DEFAULT_ACL", "private"),
                "querystring_auth": env_bool("AWS_QUERYSTRING_AUTH", True),
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }

# ---------------------------------------------------------------------------
# Database Connection Pooling
# ---------------------------------------------------------------------------
# For production with PostgreSQL, configure connection pooling
# Either use PgBouncer externally or django-db-connection-pool
DB_CONN_MAX_AGE = int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", 0 if DEBUG else 60))
if "default" in DATABASES:
    DATABASES["default"]["CONN_MAX_AGE"] = DB_CONN_MAX_AGE
    # Disable server-side cursors for connection pooling compatibility
    if IS_PRODUCTION and DB_CONN_MAX_AGE > 0:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

CACHE_URL = env_str("DJANGO_CACHE_URL")
if CACHE_URL:
    parsed_cache = urlparse(CACHE_URL)
    if parsed_cache.scheme not in {"redis", "rediss"}:
        raise ImproperlyConfigured("DJANGO_CACHE_URL must use redis:// or rediss://.")
    if not parsed_cache.hostname:
        raise ImproperlyConfigured("DJANGO_CACHE_URL must include a hostname.")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "TIMEOUT": int(env_str("DJANGO_CACHE_DEFAULT_TIMEOUT", "300")),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "webbuilder-default-cache",
        }
    }

# ---------------------------------------------------------------------------
# Celery Configuration
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env_str("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0" if DEBUG else "")
CELERY_RESULT_BACKEND = env_str("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(env_str("CELERY_TASK_TIME_LIMIT", "1800"))
CELERY_TASK_SOFT_TIME_LIMIT = int(env_str("CELERY_TASK_SOFT_TIME_LIMIT", "1500"))

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("DJANGO_LOG_FORMAT", "json" if not DEBUG else "standard")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
        "json": {
            "()": "builder.logging_config.JsonFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
        }
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_DJANGO_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "builder": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# File Upload Settings
# ---------------------------------------------------------------------------

# Maximum upload size (default 10MB, configurable via env)
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.environ.get("DJANGO_MAX_UPLOAD_SIZE", 10 * 1024 * 1024))
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE
FILE_UPLOAD_PERMISSIONS = env_octal("DJANGO_FILE_UPLOAD_PERMISSIONS", 0o640)
FILE_UPLOAD_DIRECTORY_PERMISSIONS = env_octal("DJANGO_FILE_UPLOAD_DIRECTORY_PERMISSIONS", 0o750)

# Allowed file extensions for media uploads
ALLOWED_UPLOAD_EXTENSIONS = env_list(
    "DJANGO_ALLOWED_UPLOAD_EXTENSIONS",
    [
        # Images
        "jpg", "jpeg", "png", "gif", "webp", "svg", "ico", "bmp", "tiff",
        # Documents
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "csv",
        # Video
        "mp4", "webm", "mov", "avi",
        # Audio
        "mp3", "wav", "ogg",
        # Archives
        "zip",
    ],
)

# Blocked file extensions (security)
BLOCKED_UPLOAD_EXTENSIONS = env_list(
    "DJANGO_BLOCKED_UPLOAD_EXTENSIONS",
    ["exe", "bat", "cmd", "sh", "php", "py", "js", "html", "htm", "asp", "aspx", "jsp"],
)

# Maximum file size per type (in bytes)
MAX_IMAGE_SIZE = int(os.environ.get("DJANGO_MAX_IMAGE_SIZE", 5 * 1024 * 1024))  # 5MB
MAX_VIDEO_SIZE = int(os.environ.get("DJANGO_MAX_VIDEO_SIZE", 100 * 1024 * 1024))  # 100MB
MAX_DOCUMENT_SIZE = int(os.environ.get("DJANGO_MAX_DOCUMENT_SIZE", 20 * 1024 * 1024))  # 20MB


def _validate_production_settings() -> None:
    if not IS_PRODUCTION:
        return

    if CORS_ALLOW_ALL_ORIGINS:
        raise ImproperlyConfigured("CORS_ALLOW_ALL_ORIGINS must remain false in production.")

    if not CORS_ALLOWED_ORIGINS:
        raise ImproperlyConfigured("DJANGO_CORS_ALLOWED_ORIGINS must be explicitly configured in production.")

    missing_csrf = sorted(set(CORS_ALLOWED_ORIGINS) - set(CSRF_TRUSTED_ORIGINS))
    if missing_csrf:
        raise ImproperlyConfigured(
            "DJANGO_CSRF_TRUSTED_ORIGINS must include every value from DJANGO_CORS_ALLOWED_ORIGINS. "
            f"Missing: {', '.join(missing_csrf)}"
        )

    if not SECURE_SSL_REDIRECT:
        raise ImproperlyConfigured("DJANGO_SECURE_SSL_REDIRECT must be true in production.")
    if SECURE_PROXY_SSL_HEADER != ("HTTP_X_FORWARDED_PROTO", "https"):
        raise ImproperlyConfigured("SECURE_PROXY_SSL_HEADER must be ('HTTP_X_FORWARDED_PROTO', 'https').")
    if not USE_X_FORWARDED_HOST:
        raise ImproperlyConfigured("DJANGO_USE_X_FORWARDED_HOST must be true in production.")
    if SECURE_HSTS_SECONDS < 31536000:
        raise ImproperlyConfigured("DJANGO_SECURE_HSTS_SECONDS must be at least 31536000 in production.")
    if not SECURE_HSTS_INCLUDE_SUBDOMAINS:
        raise ImproperlyConfigured("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS must be true in production.")
    if not SECURE_HSTS_PRELOAD:
        raise ImproperlyConfigured("DJANGO_SECURE_HSTS_PRELOAD must be true in production.")
    if not SESSION_COOKIE_SECURE:
        raise ImproperlyConfigured("DJANGO_SESSION_COOKIE_SECURE must be true in production.")
    if not CSRF_COOKIE_SECURE:
        raise ImproperlyConfigured("DJANGO_CSRF_COOKIE_SECURE must be true in production.")
    if SESSION_COOKIE_AGE <= 0:
        raise ImproperlyConfigured("DJANGO_SESSION_COOKIE_AGE must be a positive integer.")
    if X_FRAME_OPTIONS != "DENY":
        raise ImproperlyConfigured("DJANGO_X_FRAME_OPTIONS must be DENY in production.")

    db_config = DATABASES.get("default", {})
    db_engine = (db_config.get("ENGINE") or "").strip().lower()
    if db_engine.endswith("sqlite3"):
        raise ImproperlyConfigured("SQLite is not allowed when DJANGO_DEBUG=false. Configure PostgreSQL.")
    if not (db_config.get("NAME") or "").strip():
        raise ImproperlyConfigured("DJANGO_DB_NAME must be set in production.")
    if not (db_config.get("USER") or "").strip():
        raise ImproperlyConfigured("DJANGO_DB_USER must be set in production.")
    if not (db_config.get("PASSWORD") or "").strip():
        raise ImproperlyConfigured("DJANGO_DB_PASSWORD must be set in production.")
    _ensure_not_placeholder("DJANGO_DB_PASSWORD", db_config.get("PASSWORD", ""))

    if not CACHE_URL:
        raise ImproperlyConfigured("DJANGO_CACHE_URL must be set in production.")

    if EMAIL_BACKEND.endswith("smtp.EmailBackend"):
        if not EMAIL_HOST:
            raise ImproperlyConfigured("DJANGO_EMAIL_HOST must be set when using SMTP in production.")
        if EMAIL_USE_SSL and EMAIL_USE_TLS:
            raise ImproperlyConfigured("DJANGO_EMAIL_USE_SSL and DJANGO_EMAIL_USE_TLS cannot both be true.")
        if bool(EMAIL_HOST_USER) != bool(EMAIL_HOST_PASSWORD):
            raise ImproperlyConfigured(
                "DJANGO_EMAIL_HOST_USER and DJANGO_EMAIL_HOST_PASSWORD must both be set (or both empty)."
            )
        _ensure_not_placeholder("DJANGO_EMAIL_HOST_PASSWORD", EMAIL_HOST_PASSWORD)

    if AUTH_BOOTSTRAP_ENABLED:
        if not AUTH_BOOTSTRAP_TOKEN:
            raise ImproperlyConfigured(
                "DJANGO_AUTH_BOOTSTRAP_TOKEN must be set when DJANGO_AUTH_BOOTSTRAP_ENABLED=true in production."
            )
        if len(AUTH_BOOTSTRAP_TOKEN) < 24:
            raise ImproperlyConfigured("DJANGO_AUTH_BOOTSTRAP_TOKEN must be at least 24 characters.")

    if not METRICS_AUTH_TOKEN:
        raise ImproperlyConfigured("DJANGO_METRICS_AUTH_TOKEN must be set in production.")
    if len(METRICS_AUTH_TOKEN) < 24:
        raise ImproperlyConfigured("DJANGO_METRICS_AUTH_TOKEN must be at least 24 characters in production.")


_validate_production_settings()

# ---------------------------------------------------------------------------
# Sentry APM / Error Tracking (Production)
# ---------------------------------------------------------------------------
SENTRY_DSN = env_str("SENTRY_DSN")
SENTRY_ENVIRONMENT = env_str("SENTRY_ENVIRONMENT", "development" if DEBUG else "production")
SENTRY_TRACES_SAMPLE_RATE = float(env_str("SENTRY_TRACES_SAMPLE_RATE", "0.1" if IS_PRODUCTION else "0"))
SENTRY_PROFILES_SAMPLE_RATE = float(env_str("SENTRY_PROFILES_SAMPLE_RATE", "0.1" if IS_PRODUCTION else "0"))

if SENTRY_DSN and IS_PRODUCTION:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
            ),
            LoggingIntegration(
                level=None,  # Capture all levels
                event_level=None,  # Don't send logs as events by default
            ),
        ],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=SENTRY_PROFILES_SAMPLE_RATE,
        send_default_pii=False,  # Don't send PII by default
        attach_stacktrace=True,
        # Filter out health check transactions to reduce noise
        traces_sampler=lambda ctx: 0 if ctx.get("wsgi_environ", {}).get("PATH_INFO", "").startswith("/api/health") else SENTRY_TRACES_SAMPLE_RATE,
    )
