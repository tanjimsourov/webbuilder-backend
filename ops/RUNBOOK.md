# Runtime Runbook

## Core commands

- App health: `python manage.py service_healthcheck --component app --check-cache`
- Worker health: `python manage.py service_healthcheck --component worker --check-cache`
- Scheduler health: `python manage.py service_healthcheck --component scheduler --check-cache`
- Process jobs now: `python manage.py run_jobs --batch-size 50`
- Process scheduler once: `python manage.py run_scheduler`

## Docker service controls

- Restart backend: `docker compose restart backend`
- Restart workers: `docker compose restart queue-worker job-runner scheduler`
- Logs: `docker compose logs -f backend queue-worker job-runner scheduler`

## Key endpoints

- `/api/health/`
- `/api/ready/`
- `/api/live/`
- `/api/version/`
- `/api/metrics/` (requires token in production)