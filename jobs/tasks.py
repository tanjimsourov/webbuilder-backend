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
