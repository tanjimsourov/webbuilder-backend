# Environment Configuration

## Local Development

1. Copy `.env.example` to `.env`.
2. Keep `DJANGO_DEBUG=true` for local development.
3. Use SQLite defaults from `.env.example` unless you explicitly want PostgreSQL.
4. Run the backend with `pipenv run python manage.py runserver 127.0.0.1:8000 --noreload`.

## Generic env aliases

This repo's canonical configuration is `DJANGO_*` (validated in `config/settings.py`). For production deployments that prefer generic conventions, the following variables are supported as **aliases** and mapped into `DJANGO_*` at startup when the canonical variable is not already set:

- `APP_ENV` → influences `DJANGO_DEBUG` (production disables debug)
- `DATABASE_URL` → maps to `DJANGO_DB_*` when `DJANGO_DB_ENGINE` is not set
- `REDIS_URL` → maps to `DJANGO_CACHE_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` when missing
- `SESSION_SECRET` → maps to `DJANGO_SECRET_KEY` when missing
- `CORS_ALLOWED_ORIGINS` → maps to `DJANGO_CORS_ALLOWED_ORIGINS` when missing
- `SMTP_*` → maps to `DJANGO_EMAIL_*` when missing
- `STORAGE_DRIVER` / `STORAGE_BUCKET` → maps to `DJANGO_USE_S3_STORAGE` / `AWS_STORAGE_BUCKET_NAME` when missing

## Security-specific variables

- `DJANGO_AUTH_MAX_FAILED_LOGIN_ATTEMPTS`
- `DJANGO_AUTH_LOCKOUT_SECONDS`
- `DJANGO_AUTH_BACKOFF_MAX_SECONDS`
- `DJANGO_AUTH_ACCESS_TOKEN_TTL_SECONDS`
- `DJANGO_AUTH_REFRESH_TOKEN_TTL_SECONDS`
- `DJANGO_AUTH_MFA_CHALLENGE_TTL_SECONDS`
- `DJANGO_AUTH_EMAIL_VERIFICATION_TOKEN_TTL_SECONDS`
- `DJANGO_AUTH_PASSWORD_RESET_TOKEN_TTL_SECONDS`
- `DJANGO_PERMISSIONS_POLICY`
- `DJANGO_CONTENT_SECURITY_POLICY`
- `DJANGO_MAX_REQUEST_BODY_BYTES`
- `MALWARE_SCAN_COMMAND`

## AI / Analytics / Search variables

- `AI_DEFAULT_PROVIDER` (`mock`, `openai`, `anthropic`)
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
- `AI_DEFAULT_MAX_REQUESTS`
- `AI_DEFAULT_MAX_TOKENS`
- `AI_DEFAULT_MAX_COST_USD`
- `ANALYTICS_HASH_SALT`
- `MEILISEARCH_HOST`, `MEILISEARCH_API_KEY`

## Observability variables

- `ERROR_TRACKING_PROVIDER` (`sentry` or `none`)
- `TRACING_PROVIDER` (`opentelemetry` or `none`)
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_SERVICE_NAME`
- `SENTRY_DSN`, `SENTRY_ENVIRONMENT`
- `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`

## Startup and scheduler variables

- `DJANGO_WAIT_FOR_DB`
- `DJANGO_WAIT_FOR_CACHE`
- `DJANGO_STARTUP_MAX_WAIT_SECONDS`
- `SCHEDULER_PUBLISH_INTERVAL_SECONDS`
- `SCHEDULER_AI_CLEANUP_INTERVAL_SECONDS`
- `SCHEDULER_AI_RETENTION_DAYS`
- `SCHEDULER_TOKEN_CLEANUP_INTERVAL_SECONDS`
- `SCHEDULER_TOKEN_RETENTION_DAYS`
- `SCHEDULER_ANALYTICS_ROLLUP_INTERVAL_SECONDS`
- `SCHEDULER_ANALYTICS_ROLLUP_DAYS_BACK`

## Production Fail-Fast Rules

When `DJANGO_DEBUG=false`, startup now fails immediately unless all critical configuration is valid.

### Required variables

- `DJANGO_SECRET_KEY` (minimum 32 chars, non-placeholder)
- `DJANGO_ALLOWED_HOSTS` (comma-separated hostnames, no wildcards, no URLs)
- `DJANGO_CORS_ALLOWED_ORIGINS` (comma-separated HTTPS origins)
- `DJANGO_CSRF_TRUSTED_ORIGINS` (must include all CORS origins)
- `DJANGO_DB_ENGINE` (must not be SQLite)
- `DJANGO_DB_NAME`
- `DJANGO_DB_USER`
- `DJANGO_DB_PASSWORD` (non-placeholder)
- `DJANGO_CACHE_URL` (`redis://` or `rediss://`)
- `DJANGO_METRICS_AUTH_TOKEN` (minimum 24 chars)

### Required production-safe security values

- `DJANGO_SESSION_COOKIE_SECURE=true`
- `DJANGO_CSRF_COOKIE_SECURE=true`
- `DJANGO_SECURE_SSL_REDIRECT=true`
- `DJANGO_SECURE_HSTS_SECONDS>=31536000`
- `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=true`
- `DJANGO_SECURE_HSTS_PRELOAD=true`
- `DJANGO_USE_X_FORWARDED_HOST=true`
- `DJANGO_X_FRAME_OPTIONS=DENY`
- `DJANGO_METRICS_ALLOW_QUERY_TOKEN=false`
- `DJANGO_AUTH_MAGIC_LOGIN_ENABLED=false`

### Additional validation behavior

- `DJANGO_ALLOWED_HOSTS` cannot contain wildcard values (`*`, `.example.com`) or URLs.
- CORS wildcard behavior is disabled (`CORS_ALLOW_ALL_ORIGINS=False`).
- CORS and CSRF origins must be valid origins and cannot include wildcards.
- If `SESSION_COOKIE_SAMESITE=None` or `CSRF_COOKIE_SAMESITE=None`, the corresponding secure cookie setting must be true.
- If `PAYLOAD_CMS_ENABLED=true`, `PAYLOAD_CMS_DATABASE_URL` and `PAYLOAD_CMS_SECRET` are required.
- If `PAYLOAD_ECOMMERCE_ENABLED=true`, database, secret, and Stripe companion secrets are required.
- If `LIBRECRAWL_ENABLED=true` and `LIBRECRAWL_LOCAL_MODE=false`, `LIBRECRAWL_SECRET_KEY` is required.
- Placeholder-like secrets are rejected in production across validated integration keys.
- `DJANGO_REDIRECT_ALLOWED_EXTERNAL_HOSTS` defines the only external hosts allowed for managed URL redirects.
- `DJANGO_ALLOW_PRIVATE_WEBHOOK_TARGETS` controls whether webhook URLs may target private/loopback hosts (disabled by default in production).
- `DJANGO_PAYMENT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS` controls webhook replay protection cache lifetime.
- `MEILISEARCH_SETTINGS_SYNC_INTERVAL_SECONDS` controls how often index settings are re-synced per API process (default: `300` seconds).
- `/admin/` is blocked with a 404 response when `DJANGO_ENABLE_ADMIN=false` (default in production).

## Secrets Policy

- Do not commit `.env`.
- Keep only `.env.example` in the repository.
- Rotate any previously exposed credentials before deploying.

## Health/readiness endpoints

- `GET /api/health/` database connectivity healthcheck.
- `GET /api/live/` liveness probe.
- `GET /api/ready/` readiness probe (database + cache).
- `GET /api/version/` build/runtime metadata.
