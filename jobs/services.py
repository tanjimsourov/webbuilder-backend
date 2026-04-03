"""Jobs domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import jobs as builder_jobs


def create_job(job_type: str, payload: dict[str, Any], *, priority: int = 5, scheduled_at=None):
    """Create and persist a background job."""
    return builder_jobs.create_job(job_type, payload, priority=priority, scheduled_at=scheduled_at)


def schedule_publish(content_type: str, content_id: int, scheduled_at):
    """Schedule content publication."""
    return builder_jobs.schedule_publish(content_type, content_id, scheduled_at)


def process_pending_jobs(batch_size: int = 10) -> int:
    """Run up to ``batch_size`` pending jobs."""
    return builder_jobs.process_pending_jobs(batch_size=batch_size)


def cleanup_old_jobs(days: int = 30) -> int:
    """Delete jobs older than ``days``."""
    return builder_jobs.cleanup_old_jobs(days=days)


__all__ = [
    "cleanup_old_jobs",
    "create_job",
    "process_pending_jobs",
    "schedule_publish",
]
