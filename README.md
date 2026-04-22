# WebBuilder Backend

This repository contains a Django-based backend for a website builder
platform. It is under active restructuring to introduce modular apps,
background processing, payment integrations, and improved security.

## Modules

This is a modular Django monolith composed of multiple Django apps plus a small shared core layer.

- See `MODULES.md` for the authoritative module list and boundaries.
- See `ARCHITECTURE.md` for cross-cutting conventions (config, logging, request ids, health probes).
- See `SECURITY.md` and `SECURITY_BASELINE.md` for vulnerability reporting and hardened auth/token/upload/RBAC baselines.
- See `CONTENT_SCHEMA.md`, `BUILDER_SCHEMA.md`, and `PUBLISH_WORKFLOW.md` for CMS/builder/publish contracts.
- See `commerce/README.md` for commerce catalog/cart/checkout/order/payment/refund/inventory flows.
- See `analytics/README.md`, `shared/ai/README.md`, and `shared/seo/README.md` for analytics taxonomy, AI provider/quota config, and SEO data flow.
- See `deploy/` and `ops/` docs for deployment, backup/restore, runbooks, rollback, and migration operations.
- See `VERSIONING.md` and `VERSION` for release/version strategy.

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

2. Copy `.env.example` to `.env` and fill in required environment variables.

3. Apply migrations and run the development server:

```bash
python manage.py migrate
python manage.py runserver
```

### Package management

- Canonical dependency set for CI/Docker: `requirements.txt` + `requirements-dev.txt`.
- Developer convenience: `Pipfile` (Pipenv) is supported for local workflows (see `ENVIRONMENT.md`).

## Deployment

The project uses Docker Compose for local and deployment workflows. For
production, set `DJANGO_DEBUG=0` and configure `DJANGO_SECRET_KEY`,
`DJANGO_ALLOWED_HOSTS`, database credentials, Stripe keys, and Celery/Redis
environment variables. Keep `DJANGO_AUTH_MAGIC_LOGIN_ENABLED=false` and
`DJANGO_ENABLE_ADMIN=false` unless you intentionally expose those surfaces.

The container entrypoint now runs `migrate` and `collectstatic` by default at
startup. You can override this behavior with:

- `DJANGO_RUN_MIGRATIONS=0`
- `DJANGO_COLLECTSTATIC=0`

The `job-runner` compose service runs the durable DB-backed job queue
(`python manage.py run_jobs --daemon`) used by webhook delivery and scheduled
background operations.
The `scheduler` compose service runs periodic operational tasks (`python manage.py run_scheduler --daemon`) for scheduled publishing, AI retention cleanup, token cleanup, and analytics rollups.

### Runtime endpoints (ops)

All endpoints are mounted under `/api/`:

- `GET /api/health/` database connectivity healthcheck (used by Docker healthchecks).
- `GET /api/live/` liveness probe.
- `GET /api/ready/` readiness probe (database + cache).
- `GET /api/version/` build/runtime metadata.
- Worker/scheduler health probes are exposed through `python manage.py service_healthcheck --component <app|worker|scheduler>`.

### Security auth endpoints

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/login/mfa/`
- `POST /api/auth/logout/`
- `POST /api/auth/change-password/`
- `POST /api/auth/password-reset/request/`
- `POST /api/auth/password-reset/confirm/`
- `POST /api/auth/email-verification/request/`
- `POST /api/auth/email-verification/resend/`
- `POST /api/auth/email-verification/confirm/`
- `POST /api/auth/tokens/issue/`
- `POST /api/auth/tokens/refresh/`
- `POST /api/auth/tokens/revoke/`
- `POST /api/auth/mfa/totp/setup/`
- `POST /api/auth/mfa/totp/verify/`
- `POST /api/auth/mfa/recovery-codes/regenerate/`
- `GET /api/auth/sessions/`
- `POST /api/auth/sessions/revoke/`
- `POST /api/auth/sessions/revoke-others/`
- `GET /api/auth/activity/`
- `GET|POST /api/auth/api-keys/`
- `POST /api/auth/api-keys/{id}/revoke/`

### Multi-tenant identity and RBAC

- Core identity and tenancy tables live in `core/models.py` (`UserAccount`, `Workspace`, `WorkspaceMembership`, `SiteMembership`, `UserSession`, `SecurityToken`, `MFATOTPDevice`, `MFARecoveryCode`, `PersonalAPIKey`, `SecurityAuditLog`, `ImpersonationAudit`).
- Workspace roles: `owner`, `admin`, `editor`, `author`, `analyst`, `support`, `billing_manager`, `viewer`.
- Site roles: `site_owner`, `editor`, `author`, `analyst`, `support`, `billing_manager`, `viewer`.
- Platform operator controls are under `/api/platform-admin/*` including user lock/unlock, role assignment, workspace/site membership management, and impersonation.
- See `AUTHORIZATION.md` for auth flow, MFA, token model, tenancy boundaries, invitations, and scope conventions.

### Dependencies

- Database: SQLite for local dev; PostgreSQL for production.
- Cache/broker: Redis (required for production-like cache/broker).
- Search (optional): Meilisearch.
- Object storage (optional): S3-compatible storage (AWS S3 / MinIO) via `django-storages`.
- Email (optional): SMTP; local docker-compose includes a mail catcher.
- Provider abstraction endpoints are exposed under `/api/provider/*` and website runtime-management endpoints under `/api/website/*`.

### Commerce backend

- Admin APIs cover product catalog, variants, collections, media, discounts, customers, checkout sessions, orders, shipments, payments, refunds, inventory, tax records, and audit/event streams under `/api/`.
- Public storefront APIs cover catalog, product detail, cart operations, checkout sessions, checkout completion, shipping/tax quote, and event ingestion under `/api/public/shop/<site_slug>/...`.
- Payment intent + webhook + refund routes are available under `/api/payments/*` and `/api/payments/refund/<order_id>/`.
- Order and refund lifecycle details are documented in `commerce/README.md`.

### AI + analytics + automation

- Analytics ingestion endpoint: `POST /api/analytics/ingest/<site_slug>/` with bot filtering and privacy-aware IP handling.
- Analytics dashboard queries: `GET /api/analytics/sites/<site_id>/summary/` and `POST /api/analytics/sites/<site_id>/funnel/`.
- AI generation endpoints: `/api/provider/ai/*` with queued jobs, moderation logs, and quota metering.
- Automation/webhook events include `site.published`, `post.published`, `order.created`, `customer.created`, `form.submitted`, `ai.job.completed`, and `publish.job.completed`.

Performance/runtime notes:

- Search indexing is now queued through the DB job queue (`search_index` jobs)
  instead of blocking API write requests.
- Webhook delivery enqueueing is transaction-aware and runs after commit.
- Job claiming uses row locks (`select_for_update` with `skip_locked` when
  supported) so multiple job-runner processes can run safely without duplicate
  job execution.
- Meilisearch index settings sync is throttled in-process; control with
  `MEILISEARCH_SETTINGS_SYNC_INTERVAL_SECONDS` (default `300`).

## API Permission And Validation Notes

Workspace and site APIs now enforce role boundaries consistently:

- `owner` and `admin` can manage members and invitations.
- `editor` can edit site content but cannot manage members.
- `viewer` is read-only.
- Workspace owner actions continue to work even for legacy records where the
  owner membership row is missing.

Invitation endpoints:

- `POST /api/workspaces/accept-invitation/` accepts pending tokens.
- `POST /api/workspaces/decline-invitation/` declines pending tokens and is
  safe to call repeatedly (idempotent success response).
- `GET /api/workspaces/{id}/invitations/` requires member-management
  permission.

Template and form safety rules:

- Existing global block templates can only be modified by superusers.
- Form submissions support status updates, but core submission payload/source
  fields (`site`, `page`, `form_name`, `payload`) are immutable after create.
- Form submission list pagination (`/api/forms/{id}/submissions/`) validates
  `page` and `page_size` and returns `400` for invalid values.

## Contributing

Install git hooks after cloning:

```bash
pre-commit install
```

## Testing And Quality Gates

Run the same checks locally that CI enforces:

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check .
python manage.py check
python scripts/check_migration_drift.py
python manage.py test --verbosity 2
```

Production settings validation is covered by:

```bash
python manage.py test builder.test_settings_validation
```

Notes:

- CI runs a full Django test suite, not just selected modules.
- CI also enforces dependency integrity (`pip check`) and dependency security
  scanning (`pip-audit -r requirements.txt`).
- Migration drift checks currently target modular apps (`core`, `cms`,
  `commerce`, `forms`, `blog`, `analytics`, `notifications`, `jobs`,
  `payments`, `domains`, `email_hosting`) via
  [check_migration_drift.py](c:/Users/spicy/Documents/projects/website/web-site builder/backend/scripts/check_migration_drift.py).
- `builder` migration drift is intentionally excluded while legacy-model split
  work is still in progress.

Developer checklist before opening a PR:

1. Run `python -m ruff check .`
2. Run `python scripts/check_migration_drift.py`
3. Run `python manage.py test --verbosity 2`

## Task runner shortcuts

Use the root `Makefile` for common flows:

- `make up` / `make down`
- `make lint` / `make check` / `make test`
- `make migrate` / `make drift`
- `make jobs` / `make scheduler`
- `make bootstrap-local`
