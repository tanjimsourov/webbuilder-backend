"""Celery tasks for background processing."""

from datetime import datetime, timezone

from celery import shared_task

from cms import services as cms_services
from email_hosting import services as email_services
from email_hosting.models import EmailDomain


@shared_task
def publish_scheduled_pages() -> None:
    """Publish pages scheduled to go live.

    This placeholder keeps the periodic task surface in the jobs domain.
    Once the page lifecycle is fully migrated, replace this with an ORM query
    and call into ``cms.services`` for each due page.
    """
    now = datetime.now(timezone.utc)
    # TODO: for page in Page.objects.filter(status=Page.STATUS_DRAFT, scheduled_at__lte=now):
    #     cms_services.publish_page(page)
    _ = (now, cms_services)
    return None


@shared_task
def send_notification_email(notification_id: int | None = None) -> None:
    """Send queued notification emails.

    ``notification_id`` is optional to support batch-mode runs later.
    """
    # TODO: implement email dispatch via notifications service layer.
    _ = notification_id


@shared_task
def retry_webhook_delivery(delivery_id: int | None = None) -> None:
    """Retry failed webhook deliveries.

    ``delivery_id`` is optional to support bulk retries by schedule.
    """
    # TODO: implement webhook retry logic via notifications domain services.
    _ = delivery_id


@shared_task
def verify_pending_email_domains() -> int:
    """Periodically verify domains still pending DNS validation."""
    domains = EmailDomain.objects.filter(
        status__in=[
            EmailDomain.DomainStatus.PENDING,
            EmailDomain.DomainStatus.VERIFYING,
        ]
    ).only("id", "status", "name", "workspace_id", "site_id", "mx_record", "spf_record", "dkim_record")

    processed = 0
    for domain in domains.iterator():
        try:
            email_services.verify_email_domain(domain)
            processed += 1
        except Exception:
            # Verification errors are tracked in service logs and task history.
            continue
    return processed
