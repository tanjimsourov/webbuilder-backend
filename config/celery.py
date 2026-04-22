"""Celery application configuration for the Django project."""

from __future__ import annotations

import os
from pathlib import Path

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    from shared.config.dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

app = Celery("webbuilder")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
