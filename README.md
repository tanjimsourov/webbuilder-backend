# WebBuilder Backend

This repository contains a Django-based backend for a website builder
platform. It is under active restructuring to introduce modular apps,
background processing, payment integrations, and improved security.

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
