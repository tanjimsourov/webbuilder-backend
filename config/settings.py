import os
import sys
from pathlib import Path

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


DEBUG = env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-wordpress-clone-starter-key"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"] if DEBUG else [])
if DEBUG and "*" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, "*"]
elif not DEBUG and "*" in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [host for host in ALLOWED_HOSTS if host != "*"]

LIBRECRAWL_ENABLED = env_bool("LIBRECRAWL_ENABLED", True)
LIBRECRAWL_HOST = os.environ.get("LIBRECRAWL_HOST", "127.0.0.1")
LIBRECRAWL_PORT = int(os.environ.get("LIBRECRAWL_PORT", "5055"))
LIBRECRAWL_PUBLIC_URL = os.environ.get(
    "LIBRECRAWL_PUBLIC_URL",
    f"http://127.0.0.1:{LIBRECRAWL_PORT}" if DEBUG else "",
)
LIBRECRAWL_LOCAL_MODE = env_bool("LIBRECRAWL_LOCAL_MODE", DEBUG)
LIBRECRAWL_SECRET_KEY = os.environ.get("LIBRECRAWL_SECRET_KEY", SECRET_KEY)

SERPBEAR_ENABLED = env_bool("SERPBEAR_ENABLED", True)
SERPBEAR_HOST = os.environ.get("SERPBEAR_HOST", "127.0.0.1")
SERPBEAR_PORT = int(os.environ.get("SERPBEAR_PORT", "5060"))
SERPBEAR_PUBLIC_URL = os.environ.get(
    "SERPBEAR_PUBLIC_URL",
    f"http://127.0.0.1:{SERPBEAR_PORT}" if DEBUG else "",
)

UMAMI_ENABLED = env_bool("UMAMI_ENABLED", True)
UMAMI_HOST = os.environ.get("UMAMI_HOST", "127.0.0.1")
UMAMI_PORT = int(os.environ.get("UMAMI_PORT", "5070"))
UMAMI_PUBLIC_URL = os.environ.get(
    "UMAMI_PUBLIC_URL",
    f"http://127.0.0.1:{UMAMI_PORT}" if DEBUG else "",
)

PAYLOAD_CMS_ENABLED = env_bool("PAYLOAD_CMS_ENABLED", True)
PAYLOAD_CMS_HOST = os.environ.get("PAYLOAD_CMS_HOST", "127.0.0.1")
PAYLOAD_CMS_PORT = int(os.environ.get("PAYLOAD_CMS_PORT", "5080"))
PAYLOAD_CMS_PUBLIC_URL = os.environ.get(
    "PAYLOAD_CMS_PUBLIC_URL",
    f"http://127.0.0.1:{PAYLOAD_CMS_PORT}" if DEBUG else "",
)
PAYLOAD_CMS_DATABASE_URL = os.environ.get("PAYLOAD_CMS_DATABASE_URL", "")
PAYLOAD_CMS_SECRET = os.environ.get("PAYLOAD_CMS_SECRET", SECRET_KEY if DEBUG else "")
PAYLOAD_CMS_PREVIEW_SECRET = os.environ.get("PAYLOAD_CMS_PREVIEW_SECRET", PAYLOAD_CMS_SECRET)
PAYLOAD_CMS_CRON_SECRET = os.environ.get("PAYLOAD_CMS_CRON_SECRET", PAYLOAD_CMS_SECRET)

PAYLOAD_ECOMMERCE_ENABLED = env_bool("PAYLOAD_ECOMMERCE_ENABLED", True)
PAYLOAD_ECOMMERCE_HOST = os.environ.get("PAYLOAD_ECOMMERCE_HOST", "127.0.0.1")
PAYLOAD_ECOMMERCE_PORT = int(os.environ.get("PAYLOAD_ECOMMERCE_PORT", "5085"))
PAYLOAD_ECOMMERCE_PUBLIC_URL = os.environ.get(
    "PAYLOAD_ECOMMERCE_PUBLIC_URL",
    f"http://127.0.0.1:{PAYLOAD_ECOMMERCE_PORT}" if DEBUG else "",
)
PAYLOAD_ECOMMERCE_DATABASE_URL = os.environ.get("PAYLOAD_ECOMMERCE_DATABASE_URL", "")
PAYLOAD_ECOMMERCE_SECRET = os.environ.get("PAYLOAD_ECOMMERCE_SECRET", SECRET_KEY if DEBUG else "")
PAYLOAD_ECOMMERCE_PREVIEW_SECRET = os.environ.get("PAYLOAD_ECOMMERCE_PREVIEW_SECRET", PAYLOAD_ECOMMERCE_SECRET)
PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY = os.environ.get("PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY", "")
PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY = os.environ.get("PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY", "")
PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET = os.environ.get("PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET", "")

ENABLE_REQUEST_SEED_DATA = env_bool("DJANGO_ENABLE_REQUEST_SEED_DATA", DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
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
        "ENGINE": os.environ.get("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.environ.get("DJANGO_DB_USER", ""),
        "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
        "HOST": os.environ.get("DJANGO_DB_HOST", ""),
        "PORT": os.environ.get("DJANGO_DB_PORT", ""),
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
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ] if DEBUG else [],
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
        "public_form": os.environ.get("DJANGO_THROTTLE_PUBLIC_FORM", "30/hour"),
        "public_comment": os.environ.get("DJANGO_THROTTLE_PUBLIC_COMMENT", "20/hour"),
        "public_checkout": os.environ.get("DJANGO_THROTTLE_PUBLIC_CHECKOUT", "60/hour"),
        "webhook": os.environ.get("DJANGO_THROTTLE_WEBHOOK", "1000/minute"),
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = os.environ.get("DJANGO_X_FRAME_OPTIONS", "SAMEORIGIN" if DEBUG else "DENY")
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = os.environ.get("DJANGO_SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("DJANGO_CSRF_COOKIE_SAMESITE", "Lax")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False if DEBUG else True)
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", not DEBUG)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", not DEBUG)

# ---------------------------------------------------------------------------
# Email Configuration
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", 587))
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False)
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "noreply@smcwebbuilder.com")
SERVER_EMAIL = os.environ.get("DJANGO_SERVER_EMAIL", DEFAULT_FROM_EMAIL)

# ---------------------------------------------------------------------------
# Production Media Storage (S3-compatible)
# ---------------------------------------------------------------------------
USE_S3_STORAGE = env_bool("DJANGO_USE_S3_STORAGE", False)

if USE_S3_STORAGE:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "bucket_name": os.environ.get("AWS_STORAGE_BUCKET_NAME", ""),
                "region_name": os.environ.get("AWS_S3_REGION_NAME", "us-east-1"),
                "access_key": os.environ.get("AWS_ACCESS_KEY_ID", ""),
                "secret_key": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
                "endpoint_url": os.environ.get("AWS_S3_ENDPOINT_URL", None),
                "custom_domain": os.environ.get("AWS_S3_CUSTOM_DOMAIN", None),
                "file_overwrite": False,
                "default_acl": os.environ.get("AWS_DEFAULT_ACL", "private"),
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
    if not DEBUG and DB_CONN_MAX_AGE > 0:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

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

# ---------------------------------------------------------------------------
# Sentry APM / Error Tracking (Production)
# ---------------------------------------------------------------------------
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT", "development" if DEBUG else "production")
SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1" if not DEBUG else "0"))
SENTRY_PROFILES_SAMPLE_RATE = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1" if not DEBUG else "0"))

if SENTRY_DSN and not DEBUG:
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
