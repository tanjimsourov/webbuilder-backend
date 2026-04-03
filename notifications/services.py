"""Notifications domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import services as builder_services
from builder import jobs as builder_jobs


def trigger_webhooks(site: Any, event: str, payload: dict[str, Any]) -> None:
    """Fan out a domain event to active webhooks."""
    builder_services.trigger_webhooks(site, event, payload)


def enqueue_webhook_delivery(webhook_id: int, event: str, payload: dict[str, Any]):
    """Queue a webhook delivery job."""
    return builder_jobs.queue_webhook_delivery(webhook_id, event, payload)


__all__ = [
    "enqueue_webhook_delivery",
    "trigger_webhooks",
]
