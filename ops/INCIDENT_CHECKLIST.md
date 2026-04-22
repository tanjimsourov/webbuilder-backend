# Incident Checklist

1. Confirm impact scope (API, worker, scheduler, DB, cache).
2. Check health endpoints and service_healthcheck command.
3. Inspect recent deploys, migrations, and config changes.
4. Inspect error tracking and request-id correlated logs.
5. Stabilize traffic (rate limit, rollback, isolate failing workers).
6. Communicate status update with ETA.
7. Verify recovery and close with timeline + action items.