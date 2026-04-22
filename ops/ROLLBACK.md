# Rollback Steps

## App rollback

1. Identify previous healthy image/tag.
2. Redeploy backend and worker services with previous image.
3. Confirm `/api/ready/` and worker/scheduler health.

## Data rollback

Only perform DB restore if forward-fix is impossible.

1. Put app in maintenance mode (or stop write traffic).
2. Restore DB from latest known-good backup.
3. Restore media/object data snapshot if needed.
4. Validate schema/version compatibility before reopening traffic.

## Validation

- Run smoke checks.
- Verify auth, content publish, checkout, AI jobs, and analytics ingestion.