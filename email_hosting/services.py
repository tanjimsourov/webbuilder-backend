"""Email hosting service layer.

This module contains provisioning helpers for domains, mailboxes, and aliases.
Provider API calls are intentionally left as TODOs to be wired to the chosen
mail platform.
"""

from __future__ import annotations

import logging

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from builder import domain_services as builder_domain_services
from builder import jobs as builder_jobs
from email_hosting.models import EmailDomain, EmailProvisioningTask, MailAlias, Mailbox

logger = logging.getLogger(__name__)


def _create_task(
    *,
    workspace_id: int,
    task_type: str,
    target_id: int,
    payload: dict | None = None,
) -> EmailProvisioningTask:
    return EmailProvisioningTask.objects.create(
        workspace_id=workspace_id,
        task_type=task_type,
        target_id=str(target_id),
        payload=payload or {},
    )


def create_email_domain(name: str, workspace, site) -> EmailDomain:
    """Create a domain and queue provider provisioning.

    TODO: call external provider API to provision MX/SPF/DKIM/DMARC records.
    """
    domain = EmailDomain.objects.create(
        name=name.strip().lower(),
        workspace=workspace,
        site=site,
        status=EmailDomain.DomainStatus.PENDING,
    )
    _create_task(
        workspace_id=workspace.id,
        task_type=EmailProvisioningTask.TaskType.CREATE_DOMAIN,
        target_id=domain.id,
        payload={"domain": domain.name},
    )
    # Queue a background verification pass.
    builder_jobs.create_job("verify_email_domain", {"email_domain_id": domain.id})
    logger.info("Created email domain %s", domain.name)
    return domain


def verify_email_domain(domain: EmailDomain) -> None:
    """Verify DNS records for the domain.

    TODO: validate MX records via provider API and DKIM/SPF alignment checks.
    """
    domain.status = EmailDomain.DomainStatus.VERIFYING
    domain.save(update_fields=["status", "updated_at"])

    try:
        txt_records = builder_domain_services.lookup_dns_txt(domain.name)
        has_spf = any(record.lower().startswith("v=spf1") for record in txt_records) or bool(domain.spf_record)
        has_dkim = bool(domain.dkim_record)
        has_mx = bool(domain.mx_record)

        if has_spf and has_dkim and has_mx:
            domain.status = EmailDomain.DomainStatus.ACTIVE
            domain.verified_at = timezone.now()
        else:
            domain.status = EmailDomain.DomainStatus.PENDING

        domain.save(update_fields=["status", "verified_at", "updated_at"])
        _create_task(
            workspace_id=domain.workspace_id,
            task_type=EmailProvisioningTask.TaskType.VERIFY_DOMAIN,
            target_id=domain.id,
            payload={"status": domain.status},
        )
    except Exception:
        logger.exception("Failed to verify email domain %s", domain.name)
        domain.status = EmailDomain.DomainStatus.FAILED
        domain.save(update_fields=["status", "updated_at"])
        raise


def create_mailbox(domain: EmailDomain, local_part: str, user, quota_mb: int = 1024) -> Mailbox:
    """Create a mailbox under a domain.

    TODO: call provider API to create mailbox and sync credential state.
    """
    mailbox = Mailbox.objects.create(
        domain=domain,
        site=domain.site,
        workspace=domain.workspace,
        local_part=local_part.strip().lower(),
        password_hash=make_password(None),
        quota_mb=quota_mb,
        user=user,
    )
    _create_task(
        workspace_id=domain.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_MAILBOX,
        target_id=mailbox.id,
        payload={"mailbox": mailbox.email_address},
    )
    builder_jobs.create_job("provision_mailbox", {"mailbox_id": mailbox.id})
    logger.info("Created mailbox %s", mailbox.email_address)
    return mailbox


def create_alias(domain: EmailDomain, source: str, destination_mailbox: Mailbox) -> MailAlias:
    """Create a forwarding alias.

    TODO: call provider API to configure forwarding on the mail system.
    """
    alias = MailAlias.objects.create(
        site=domain.site,
        workspace=domain.workspace,
        source_address=source.strip().lower(),
        destination_mailbox=destination_mailbox,
    )
    _create_task(
        workspace_id=domain.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_ALIAS,
        target_id=alias.id,
        payload={"source": alias.source_address, "destination": destination_mailbox.email_address},
    )
    builder_jobs.create_job("provision_mail_alias", {"alias_id": alias.id})
    logger.info("Created alias %s", alias.source_address)
    return alias


def queue_domain_verification(email_domain_id: int):
    """Queue background verification for an email domain."""
    return builder_jobs.create_job("verify_email_domain", {"email_domain_id": email_domain_id})


def queue_mailbox_provisioning(mailbox_id: int):
    """Queue mailbox provisioning work."""
    return builder_jobs.create_job("provision_mailbox", {"mailbox_id": mailbox_id})


def queue_alias_provisioning(alias_id: int):
    """Queue mail alias provisioning work."""
    return builder_jobs.create_job("provision_mail_alias", {"alias_id": alias_id})


__all__ = [
    "create_alias",
    "create_email_domain",
    "create_mailbox",
    "queue_alias_provisioning",
    "queue_domain_verification",
    "queue_mailbox_provisioning",
    "verify_email_domain",
]
