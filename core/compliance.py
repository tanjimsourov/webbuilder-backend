from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import (
    ConsentRecord,
    DataDeletionJob,
    DataExportJob,
    SecurityAuditLog,
    UserAccount,
    UserSecurityState,
    UserSession,
)


def _user_profile_payload(user) -> dict:
    account = getattr(user, "account", None)
    state = getattr(user, "security_state", None)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "date_joined": user.date_joined,
            "last_login": user.last_login,
        },
        "account": (
            {
                "status": account.status,
                "email_verified_at": account.email_verified_at,
                "display_name": account.display_name,
                "avatar_url": account.avatar_url,
                "profile_bio": account.profile_bio,
                "timezone": account.timezone,
                "locale": account.locale,
                "marketing_opt_in": account.marketing_opt_in,
                "terms_accepted_at": account.terms_accepted_at,
                "privacy_accepted_at": account.privacy_accepted_at,
                "data_processing_consent_at": account.data_processing_consent_at,
            }
            if account
            else {}
        ),
        "security_state": (
            {
                "failed_login_count": state.failed_login_count,
                "locked_until": state.locked_until,
                "last_password_change_at": state.last_password_change_at,
                "last_mfa_at": state.last_mfa_at,
            }
            if state
            else {}
        ),
    }


def process_data_export_job(export_job: DataExportJob) -> DataExportJob:
    export_job.status = DataExportJob.STATUS_PROCESSING
    export_job.save(update_fields=["status", "updated_at"])

    user = export_job.target_user
    payload = _user_profile_payload(user)
    payload["consents"] = list(
        ConsentRecord.objects.filter(user=user)
        .order_by("-created_at")
        .values("consent_type", "status", "policy_version", "source", "created_at")
    )
    payload["sessions"] = list(
        UserSession.objects.filter(user=user)
        .order_by("-created_at")
        .values("auth_method", "device_name", "ip_address", "created_at", "last_seen_at", "revoked_at")
    )
    payload["security_audit"] = list(
        SecurityAuditLog.objects.filter(actor=user).order_by("-created_at").values("action", "success", "created_at")[:500]
    )

    export_job.result_payload = payload
    export_job.error_message = ""
    export_job.status = DataExportJob.STATUS_COMPLETED
    export_job.processed_at = timezone.now()
    export_job.expires_at = timezone.now() + timedelta(days=7)
    export_job.save(
        update_fields=[
            "result_payload",
            "error_message",
            "status",
            "processed_at",
            "expires_at",
            "updated_at",
        ]
    )
    return export_job


def process_data_deletion_job(deletion_job: DataDeletionJob) -> DataDeletionJob:
    if deletion_job.status not in {
        DataDeletionJob.STATUS_APPROVED,
        DataDeletionJob.STATUS_PROCESSING,
        DataDeletionJob.STATUS_REQUESTED,
    }:
        return deletion_job

    deletion_job.status = DataDeletionJob.STATUS_PROCESSING
    deletion_job.save(update_fields=["status", "updated_at"])

    user = deletion_job.target_user
    account = getattr(user, "account", None)
    with transaction.atomic():
        UserSession.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now(), updated_at=timezone.now())
        if account:
            account.status = UserAccount.STATUS_DELETED
            account.display_name = ""
            account.avatar_url = ""
            account.profile_bio = ""
            account.metadata = {**(account.metadata or {}), "deleted_at": timezone.now().isoformat()}
            account.save(
                update_fields=[
                    "status",
                    "display_name",
                    "avatar_url",
                    "profile_bio",
                    "metadata",
                    "updated_at",
                ]
            )
        UserSecurityState.objects.filter(user=user).update(
            failed_login_count=0,
            locked_until=None,
            updated_at=timezone.now(),
        )

        anonymized_email = f"deleted+{user.id}@deleted.local"
        user.email = anonymized_email
        user.first_name = ""
        user.last_name = ""
        user.is_active = False
        user.save(update_fields=["email", "first_name", "last_name", "is_active"])

    deletion_job.status = DataDeletionJob.STATUS_COMPLETED
    deletion_job.error_message = ""
    deletion_job.processed_at = timezone.now()
    deletion_job.save(update_fields=["status", "error_message", "processed_at", "updated_at"])
    return deletion_job


def request_data_export(*, requested_by, target_user=None, workspace=None, site=None) -> DataExportJob:
    from jobs.services import create_job

    user = target_user or requested_by
    export_job = DataExportJob.objects.create(
        requested_by=requested_by,
        target_user=user,
        workspace=workspace,
        site=site,
        status=DataExportJob.STATUS_QUEUED,
        metadata={"source": "api"},
    )
    job = create_job(
        "compliance_export_data",
        {"export_job_id": export_job.id},
        priority=10,
        max_retries=3,
        idempotency_key=f"compliance_export:{export_job.id}",
    )
    export_job.queued_job_id = job.job_id
    export_job.save(update_fields=["queued_job_id", "updated_at"])
    return export_job


def request_data_deletion(*, requested_by, target_user=None, workspace=None, site=None, reason: str = "") -> DataDeletionJob:
    from jobs.services import create_job

    user = target_user or requested_by
    deletion_job = DataDeletionJob.objects.create(
        requested_by=requested_by,
        target_user=user,
        workspace=workspace,
        site=site,
        status=DataDeletionJob.STATUS_APPROVED if requested_by == user else DataDeletionJob.STATUS_REQUESTED,
        reason=(reason or "")[:280],
        metadata={"source": "api"},
    )
    if deletion_job.status == DataDeletionJob.STATUS_APPROVED:
        job = create_job(
            "compliance_delete_data",
            {"deletion_job_id": deletion_job.id},
            priority=20,
            max_retries=2,
            idempotency_key=f"compliance_delete:{deletion_job.id}",
        )
        deletion_job.queued_job_id = job.job_id
        deletion_job.save(update_fields=["queued_job_id", "updated_at"])
    return deletion_job


def cleanup_security_audit_logs(*, retention_days: int = 365) -> int:
    retention_days = max(1, min(int(retention_days), 3650))
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = SecurityAuditLog.objects.filter(created_at__lt=cutoff).delete()
    return int(deleted)
