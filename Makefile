PY ?= python
COMPOSE ?= docker compose

.PHONY: install lint typecheck check test migrate drift build up down logs ps shell worker jobs scheduler bootstrap-local backup-db restore-db

install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

lint:
	$(PY) -m ruff check .

typecheck:
	@if [ -f "mypy.ini" ] || [ -f ".mypy.ini" ] || [ -f "pyproject.toml" ]; then \
		mypy . --ignore-missing-imports; \
	else \
		echo "No mypy configuration detected; skipping typecheck."; \
	fi

check:
	$(PY) manage.py check

test:
	$(PY) manage.py test --verbosity 2

migrate:
	$(PY) manage.py migrate --noinput

drift:
	$(PY) scripts/check_migration_drift.py

build:
	docker build -t webbuilder/backend:local -f Dockerfile .

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f backend queue-worker job-runner scheduler

ps:
	$(COMPOSE) ps

shell:
	$(PY) manage.py shell

worker:
	$(PY) manage.py service_healthcheck --component worker --check-cache

jobs:
	$(PY) manage.py run_jobs --daemon --interval 5 --batch-size 20

scheduler:
	$(PY) manage.py run_scheduler --daemon --interval 60

bootstrap-local:
	$(PY) manage.py bootstrap_local

backup-db:
	$(PY) scripts/backup_database.py --output ./var/backups

restore-db:
	@if [ -z "$(FILE)" ]; then echo "Usage: make restore-db FILE=./var/backups/<backup>.sql.gz"; exit 1; fi
	$(PY) scripts/restore_database.py --input $(FILE)
