from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from provider.models import AIJob, AIModerationLog, AIUsageRecord


def cleanup_ai_generation_records(*, retention_days: int = 90) -> dict[str, int]:
    retention_days = max(1, min(int(retention_days), 3650))
    cutoff = timezone.now() - timedelta(days=retention_days)

    stale_jobs = AIJob.objects.filter(
        status__in=[AIJob.STATUS_COMPLETED, AIJob.STATUS_FAILED, AIJob.STATUS_CANCELLED],
        completed_at__isnull=False,
        completed_at__lt=cutoff,
    )
    job_ids = list(stale_jobs.values_list("id", flat=True))

    deleted_moderation = AIModerationLog.objects.filter(job_id__in=job_ids).delete()[0] if job_ids else 0
    deleted_usage = AIUsageRecord.objects.filter(job_id__in=job_ids).delete()[0] if job_ids else 0
    deleted_jobs = stale_jobs.delete()[0]

    return {
        "retention_days": retention_days,
        "deleted_jobs": int(deleted_jobs),
        "deleted_usage_records": int(deleted_usage),
        "deleted_moderation_logs": int(deleted_moderation),
    }
