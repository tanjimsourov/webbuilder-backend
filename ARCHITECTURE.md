# Architecture

This backend is a **modular Django monolith** (Django + Django REST Framework) designed as a platform with multiple domain apps. The codebase favors clear app boundaries while sharing cross-cutting infrastructure through a small `shared/` core layer.

## High-level layout

- `config/`: Django project configuration (settings, ASGI/WSGI, root URLs, Celery app).
- Domain apps (Django apps): `core/`, `cms/`, `commerce/`, `forms/`, `blog/`, `website/`, `provider/`, `analytics/`, `notifications/`, `jobs/`, `payments/`, `domains/`, `email_hosting/`.
- `builder/`: legacy monolith app that still hosts platform/system endpoints and some in-progress extractions.
- `shared/`: framework-agnostic infrastructure (env aliases, request context, logging filters, error model, contracts, search abstraction).

## Boundaries and ownership

- Each domain app owns its **models**, **serializers**, **services**, and **API routes** (`urls.py`).
- Cross-cutting concerns live in `shared/` and must not import domain apps.
- `config/urls.py` composes app routes; avoid mounting domain routes from `builder/`.

## Configuration conventions

- Canonical runtime configuration is `DJANGO_*` (see `config/settings.py`).
- Generic deployment variables like `APP_ENV`, `DATABASE_URL`, and `REDIS_URL` are supported as **aliases** and mapped into `DJANGO_*` at startup via `shared/config/aliases.py`.

## Observability

- Structured logging is enabled via `config/settings.py` and `builder/logging_config.py`.
- `shared/http/middleware.py` propagates `X-Request-ID` and injects it into logs via `shared/logger/filters.py`.
- Sensitive security actions are captured in `core.SecurityAuditLog` via `shared/auth/audit.py`.

## Security primitives

- Account lockout/backoff and failed-login tracking: `shared/auth/lockout.py` + `core.UserSecurityState`.
- Single-use security tokens (email verification, password reset, refresh rotation): `core.SecurityToken` + `shared/auth/tokens.py`.
- API key hashing and revocation: `core.PersonalAPIKey`.
- Multi-tenant identity/RBAC model: see `AUTHORIZATION.md` (`UserAccount`, workspace/site memberships, MFA, API scopes, impersonation/audit).
- Upload hardening: `builder/upload_validation.py` + `shared/storage/uploads.py`.

## Health and runtime endpoints

The platform exposes orchestration endpoints under `/api/`:

- `/api/health/`: DB connectivity (existing behavior; used by Docker healthchecks).
- `/api/live/`: liveness probe.
- `/api/ready/`: readiness probe (DB + cache).
- `/api/version/`: build/runtime metadata.

## Dependencies

- Database: SQLite for local dev, PostgreSQL for production.
- Cache/broker: Redis (also used for Celery in production-like setups).
- Search: Meilisearch (optional; indexing work is queued).
- Object storage: local filesystem for dev, S3-compatible (e.g. MinIO) for production-like workflows.
