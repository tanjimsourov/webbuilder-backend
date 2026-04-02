"""Celery tasks for background processing."""

from celery import shared_task


@shared_task
def publish_scheduled_pages() -> int:
    """Publish pages whose scheduled timestamp has elapsed."""
    # TODO: implement page publishing workflow.
    return 0


@shared_task
def send_notification_email(notification_id: int) -> None:
    """Send a queued notification email by id."""
    # TODO: implement email dispatch using notifications services.
    _ = notification_id


@shared_task
def retry_webhook_delivery(delivery_id: int) -> None:
    """Retry a failed webhook delivery by id."""
    # TODO: implement webhook retry logic.
    _ = delivery_id
