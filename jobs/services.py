"""Jobs domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import jobs as builder_jobs


def create_job(
    job_type: str,
    payload: dict[str, Any],
    *,
    priority: int = 5,
    scheduled_at=None,
    max_retries: int = 3,
    idempotency_key: str | None = None,
):
    """Create and persist a background job."""
    return builder_jobs.create_job(
        job_type,
        payload,
        priority=priority,
        scheduled_at=scheduled_at,
        max_retries=max_retries,
        idempotency_key=idempotency_key,
    )


def create_job_with_retry(
    job_type: str,
    payload: dict[str, Any],
    *,
    priority: int = 5,
    scheduled_at=None,
    max_retries: int = 3,
    idempotency_key: str | None = None,
):
    """Create a job with explicit retry/idempotency controls."""
    return builder_jobs.create_job(
        job_type,
        payload,
        priority=priority,
        scheduled_at=scheduled_at,
        max_retries=max_retries,
        idempotency_key=idempotency_key,
    )


def schedule_publish(content_type: str, content_id: int, scheduled_at):
    """Schedule content publication."""
    return builder_jobs.schedule_publish(content_type, content_id, scheduled_at)


def enqueue_runtime_revalidation(
    *,
    site_id: int,
    site_slug: str,
    event: str,
    paths: list[str],
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    priority: int = 10,
):
    """Enqueue Next.js runtime route revalidation as a background job."""
    return create_job_with_retry(
        "runtime_revalidate",
        {
            "site_id": site_id,
            "site_slug": site_slug,
            "event": event,
            "reason": reason,
            "paths": paths,
            "metadata": metadata or {},
        },
        priority=priority,
        max_retries=5,
        idempotency_key=f"runtime_revalidate:{site_id}:{event}:{','.join(paths)}",
    )


def process_pending_jobs(batch_size: int = 10) -> int:
    """Run up to ``batch_size`` pending jobs."""
    return builder_jobs.process_pending_jobs(batch_size=batch_size)


def cleanup_old_jobs(days: int = 30) -> int:
    """Delete jobs older than ``days``."""
    return builder_jobs.cleanup_old_jobs(days=days)


__all__ = [
    "cleanup_old_jobs",
    "create_job",
    "create_job_with_retry",
    "enqueue_runtime_revalidation",
    "process_pending_jobs",
    "schedule_publish",
]
