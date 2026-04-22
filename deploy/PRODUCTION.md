# Production Deployment

## Rollout model

- Blue/green or rolling deployment with health-gated cutover.
- New app versions should not serve traffic until:
  - dependency wait passes
  - migrations complete
  - readiness endpoint reports healthy

## Pre-deploy checklist

- Release tag created (`vX.Y.Z`)
- Database backup completed
- Rollback plan and previous image digest captured
- Maintenance communication prepared

## Deploy steps

1. Pull release image.
2. Start application with `DJANGO_RUN_MIGRATIONS=1` on one instance only.
3. Start worker stack (`queue-worker`, `job-runner`, `scheduler`).
4. Validate `/api/ready/` and worker/scheduler healthchecks.
5. Shift traffic gradually.
6. Monitor error rate, p95 latency, and queue depth.

## Post-deploy

- Confirm scheduled publishing executes.
- Confirm token cleanup and analytics rollups are running.
- Confirm AI retention cleanup processed successfully.