"""Django project package initialization."""

try:
    from config.celery import app as celery_app
except ModuleNotFoundError:  # pragma: no cover - celery optional until installed
    celery_app = None

__all__ = ["celery_app"]
