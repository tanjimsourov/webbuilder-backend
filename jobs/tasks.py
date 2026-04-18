"""Celery tasks for background processing."""

import logging

from django.utils import timezone

from builder.models import PlatformEmailCampaign, WebhookDelivery
from builder.platform_admin_services import send_platform_campaign
from cms import services as cms_services
from email_hosting import services as email_services
from email_hosting.models import EmailDomain
from jobs.services import create_job_with_retry

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    def shared_task(*task_args, **task_kwargs):
        if task_args and callable(task_args[0]) and len(task_args) == 1 and not task_kwargs:
            return task_args[0]

        def decorator(func):
            if task_kwargs.get("bind"):
                class _FallbackTask:
                    @staticmethod
                    def retry(exc):
                        raise exc

                def wrapped(*args, **kwargs):
                    return func(_FallbackTask(), *args, **kwargs)

                return wrapped
            return func

        return decorator


@shared_task
def publish_scheduled_pages() -> None:
    """Publish pages scheduled to go live.

    Delegates to CMS service-owned scheduling logic to keep behavior consistent
    between manual jobs and periodic execution.
    """
    cms_services.publish_due_pages()
    return None


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def runtime_revalidate(self, payload: dict | None = None) -> dict:
    """Execute a Next.js runtime revalidation call with retries."""
    try:
        return cms_services.process_runtime_revalidation_job(payload or {})
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task
def send_notification_email(notification_id: int | None = None) -> dict:
    """Send platform email campaigns by id or queue-ready state.

    ``notification_id`` maps to ``PlatformEmailCampaign.id``.
    """
    campaigns = PlatformEmailCampaign.objects.filter(status=PlatformEmailCampaign.STATUS_DRAFT)
    if notification_id is not None:
        campaigns = campaigns.filter(pk=notification_id)
    campaigns = campaigns.order_by("created_at")[:10]

    sent = 0
    failed = 0
    for campaign in campaigns:
        updated = send_platform_campaign(campaign)
        if updated.status == PlatformEmailCampaign.STATUS_SENT:
            sent += 1
        else:
            failed += 1
            logger.warning("Platform campaign %s failed to send: %s", updated.id, updated.last_error)
    return {"processed": len(campaigns), "sent": sent, "failed": failed}


@shared_task
def retry_webhook_delivery(delivery_id: int | None = None) -> dict:
    """Queue webhook retries for one or many pending/failed deliveries.

    ``delivery_id`` is optional; when omitted, due deliveries are retried in bulk.
    """
    deliveries = WebhookDelivery.objects.select_related("webhook")
    if delivery_id is not None:
        deliveries = deliveries.filter(pk=delivery_id)
    else:
        now = timezone.now()
        deliveries = deliveries.filter(
            status__in=[WebhookDelivery.STATUS_PENDING, WebhookDelivery.STATUS_FAILED],
            next_attempt_at__isnull=False,
            next_attempt_at__lte=now,
        )

    queued = 0
    for delivery in deliveries[:200]:
        create_job_with_retry(
            "deliver_webhook",
            {"delivery_id": delivery.id},
            priority=10,
            max_retries=max(1, delivery.max_attempts - delivery.attempt_count),
            idempotency_key=f"retry_delivery:{delivery.id}:{delivery.attempt_count}",
        )
        queued += 1
    return {"queued": queued}


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


@shared_task
def provision_email_domain_task(email_domain_id: int, provisioning_task_id: int | None = None) -> dict:
    """Provision a newly created email domain in the configured provider."""
    domain = email_services.provision_email_domain(
        email_domain_id,
        provisioning_task_id=provisioning_task_id,
        queue_verification=True,
    )
    return {"email_domain_id": domain.id, "domain": domain.name, "status": domain.status}


@shared_task
def verify_email_domain_task(email_domain_id: int, provisioning_task_id: int | None = None) -> dict:
    """Run DNS readiness verification for one email domain."""
    return email_services.verify_email_domain(email_domain_id, provisioning_task_id=provisioning_task_id)


@shared_task
def provision_mailbox_task(mailbox_id: int, provisioning_task_id: int | None = None) -> dict:
    """Provision mailbox in provider backend."""
    mailbox = email_services.provision_mailbox(mailbox_id, provisioning_task_id=provisioning_task_id)
    return {"mailbox_id": mailbox.id, "email": mailbox.email_address}


@shared_task
def sync_mailbox_task(mailbox_id: int, provisioning_task_id: int | None = None) -> dict:
    """Sync mailbox active/password state with provider backend."""
    mailbox = email_services.sync_mailbox(mailbox_id, provisioning_task_id=provisioning_task_id)
    return {"mailbox_id": mailbox.id, "email": mailbox.email_address, "is_active": mailbox.is_active}


@shared_task
def provision_alias_task(alias_id: int, provisioning_task_id: int | None = None) -> dict:
    """Provision alias forwarding in provider backend."""
    alias = email_services.provision_alias(alias_id, provisioning_task_id=provisioning_task_id)
    return {"alias_id": alias.id, "source": alias.source_address}


@shared_task
def sync_alias_task(alias_id: int, provisioning_task_id: int | None = None) -> dict:
    """Sync alias active state with provider backend."""
    alias = email_services.sync_alias(alias_id, provisioning_task_id=provisioning_task_id)
    return {"alias_id": alias.id, "source": alias.source_address, "active": alias.active}
