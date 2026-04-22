# Migration Operations

## Pre-migration

- Ensure backup exists.
- Run `python scripts/check_migration_drift.py`.
- Review migration SQL if risky/large.

## Deploy-time migration

- Run once per rollout: `python manage.py migrate --noinput`.
- Do not run parallel schema migrations from multiple instances.

## Post-migration checks

- `python manage.py check`
- `/api/ready/`
- Verify write paths for auth, CMS, commerce, and analytics ingestion.

## Failure handling

- If migration fails before commit: fix and rerun.
- If partial deploy after migration: roll app forward to compatible code.
- Prefer forward-fix over schema rollback when possible.