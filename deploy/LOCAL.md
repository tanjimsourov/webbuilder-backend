# Local Deployment

## Prerequisites

- Docker and Docker Compose v2
- `.env` created from `.env.example`

## Start full stack

```bash
docker compose up -d --build
```

Services started:

- `backend` (`:8000`)
- `postgres` (`:5432`)
- `redis` (`:6379`)
- `meilisearch` (`:7700`)
- `minio` (`:9000`, console `:9001`)
- `mailpit` (`:1025`, UI `:8025`)
- `queue-worker`
- `job-runner`
- `scheduler`

## Optional edge proxy

```bash
docker compose --profile edge up -d nginx
```

This exposes NGINX on `http://127.0.0.1:8080`.

## Verify readiness

```bash
curl -fsS http://127.0.0.1:8000/api/health/
curl -fsS http://127.0.0.1:8000/api/ready/
curl -fsS http://127.0.0.1:8000/api/live/
```

## Seed local bootstrap data

```bash
python manage.py bootstrap_local
```

## Stop

```bash
docker compose down
```
