# Staging Deployment

## Goal

Run production-like configuration with controlled traffic and full observability before production release.

## Required differences from local

- `DJANGO_DEBUG=false`
- Strong secrets for all required env vars
- Staging DB/Redis/S3-compatible storage
- `ERROR_TRACKING_PROVIDER=sentry`
- Optional tracing (`TRACING_PROVIDER=opentelemetry`)

## Deployment sequence

1. Build image from release candidate commit.
2. Apply DB migrations:
   - `python manage.py migrate --noinput`
3. Run health checks:
   - `/api/health/`, `/api/ready/`, `/api/live/`, `/api/version/`
4. Validate scheduler and workers are healthy.
5. Run smoke tests and migration drift checks.

## Staging gates

- No failed migrations
- No failing worker/scheduler healthchecks
- Error rate below baseline for at least 15 minutes
- Dashboard and metrics endpoint accessible