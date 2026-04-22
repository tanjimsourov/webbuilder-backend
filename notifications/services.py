"""Notifications domain services."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from django.utils import timezone

from typing import Any

from builder import jobs as builder_jobs
from builder import services as builder_services
from notifications.models import Notification, WebhookEndpoint, WebhookEndpointDelivery


def trigger_webhooks(site: Any, event: str, payload: dict[str, Any]) -> None:
    """Fan out a domain event to active webhooks."""
    builder_services.trigger_webhooks(site, event, payload)
    trigger_integration_webhooks(site=site, event=event, payload=payload)


def enqueue_webhook_delivery(webhook_id: int, event: str, payload: dict[str, Any]):
    """Queue a webhook delivery job."""
    return builder_jobs.queue_webhook_delivery(webhook_id, event, payload)


def enqueue_automation_delivery(webhook_id: int, event: str, payload: dict[str, Any]):
    """Queue an automation webhook delivery job."""
    return builder_jobs.queue_automation_webhook_delivery(webhook_id, event, payload)


def _event_matches(subscriptions: Iterable[str], event: str) -> bool:
    normalized = {str(item or "").strip() for item in subscriptions if str(item or "").strip()}
    if not normalized:
        return False
    if event in normalized:
        return True
    wildcard = [value[:-1] for value in normalized if value.endswith("*")]
    return any(event.startswith(prefix) for prefix in wildcard)


def trigger_integration_webhooks(*, site=None, workspace=None, event: str, payload: dict[str, Any]) -> int:
    queryset = WebhookEndpoint.objects.filter(status=WebhookEndpoint.STATUS_ACTIVE)
    if site is not None:
        queryset = queryset.filter(site=site)
    elif workspace is not None:
        queryset = queryset.filter(workspace=workspace)
    else:
        queryset = queryset.none()

    queued = 0
    now = timezone.now()
    for endpoint in queryset:
        if not _event_matches(endpoint.subscribed_events if isinstance(endpoint.subscribed_events, list) else [], event):
            continue
        delivery = WebhookEndpointDelivery.objects.create(
            endpoint=endpoint,
            event=event,
            payload=payload,
            status=WebhookEndpointDelivery.STATUS_PENDING,
            max_attempts=max(1, int(endpoint.max_attempts or 5)),
            next_attempt_at=now,
        )
        builder_jobs.create_job(
            job_type="deliver_integration_webhook",
            payload={"delivery_id": delivery.id},
            priority=10,
            max_retries=max(1, int(delivery.max_attempts)),
            idempotency_key=f"integration_webhook:{delivery.id}",
        )
        queued += 1
    return queued


def create_in_app_notification(
    *,
    recipient,
    subject: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
    workspace=None,
    site=None,
) -> Notification:
    return Notification.objects.create(
        recipient=recipient,
        workspace=workspace,
        site=site,
        channel=Notification.CHANNEL_IN_APP,
        status=Notification.STATUS_SENT,
        subject=subject[:255],
        body=body,
        payload=payload or {},
        delivered_at=timezone.now(),
    )


def queue_email_notification(
    *,
    recipient,
    subject: str,
    body: str,
    payload: dict[str, Any] | None = None,
    workspace=None,
    site=None,
) -> Notification:
    notification = Notification.objects.create(
        recipient=recipient,
        workspace=workspace,
        site=site,
        channel=Notification.CHANNEL_EMAIL,
        status=Notification.STATUS_PENDING,
        subject=subject[:255],
        body=body,
        payload=payload or {},
    )
    builder_jobs.create_job(
        job_type="deliver_notification_email",
        payload={"notification_id": notification.id},
        priority=10,
        max_retries=5,
        idempotency_key=f"notification_email:{notification.id}",
    )
    return notification


def mark_notification_read(notification: Notification) -> Notification:
    notification.status = Notification.STATUS_READ
    notification.read_at = timezone.now()
    notification.save(update_fields=["status", "read_at", "updated_at"])
    return notification


def retention_cleanup_notifications(*, retention_days: int = 180) -> int:
    cutoff = timezone.now() - timedelta(days=max(1, int(retention_days)))
    deleted, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
    return int(deleted)


__all__ = [
    "create_in_app_notification",
    "enqueue_automation_delivery",
    "enqueue_webhook_delivery",
    "mark_notification_read",
    "queue_email_notification",
    "retention_cleanup_notifications",
    "trigger_integration_webhooks",
    "trigger_webhooks",
]
