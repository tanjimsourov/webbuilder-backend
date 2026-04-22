from __future__ import annotations

import os
import secrets
import subprocess
import sys


MIGRATION_DRIFT_APPS = [
    "core",
    "cms",
    "commerce",
    "forms",
    "blog",
    "analytics",
    "notifications",
    "jobs",
    "payments",
    "domains",
    "email_hosting",
]


def main() -> int:
    env = os.environ.copy()
    # Keep the drift check runnable in local dev shells where .env is not loaded.
    env.setdefault("DJANGO_DEBUG", "true")
    env.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(48))
    env.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

    command = [
        sys.executable,
        "manage.py",
        "makemigrations",
        "--check",
        "--dry-run",
        *MIGRATION_DRIFT_APPS,
    ]
    completed = subprocess.run(command, env=env)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
