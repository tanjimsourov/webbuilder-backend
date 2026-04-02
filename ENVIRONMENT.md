# Environment Configuration

## Local Development

1. Copy `.env.example` to `.env`.
2. Keep `DJANGO_DEBUG=true` for local development.
3. Use SQLite defaults from `.env.example` unless you explicitly want PostgreSQL.
4. Run the backend with `pipenv run python manage.py runserver 127.0.0.1:8000 --noreload`.

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

### Additional validation behavior

- `DJANGO_ALLOWED_HOSTS` cannot contain wildcard values (`*`, `.example.com`) or URLs.
- CORS wildcard behavior is disabled (`CORS_ALLOW_ALL_ORIGINS=False`).
- CORS and CSRF origins must be valid origins and cannot include wildcards.
- If `SESSION_COOKIE_SAMESITE=None` or `CSRF_COOKIE_SAMESITE=None`, the corresponding secure cookie setting must be true.
- If `PAYLOAD_CMS_ENABLED=true`, `PAYLOAD_CMS_DATABASE_URL` and `PAYLOAD_CMS_SECRET` are required.
- If `PAYLOAD_ECOMMERCE_ENABLED=true`, database, secret, and Stripe companion secrets are required.
- If `LIBRECRAWL_ENABLED=true` and `LIBRECRAWL_LOCAL_MODE=false`, `LIBRECRAWL_SECRET_KEY` is required.
- Placeholder-like secrets are rejected in production across validated integration keys.

## Secrets Policy

- Do not commit `.env`.
- Keep only `.env.example` in the repository.
- Rotate any previously exposed credentials before deploying.
