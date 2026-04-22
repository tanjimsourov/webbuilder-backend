from __future__ import annotations

from jobs.services import create_job


def enqueue_ai_job(ai_job_id: int):
    return create_job(
        "ai_generate",
        {"ai_job_id": int(ai_job_id)},
        priority=10,
        max_retries=3,
        idempotency_key=f"ai_generate:{int(ai_job_id)}",
    )


def enqueue_search_index(object_type: str, object_id: int, *, operation: str = "upsert"):
    return create_job(
        "search_index",
        {"object_type": str(object_type), "object_id": int(object_id), "operation": str(operation)},
        priority=5,
        max_retries=3,
        idempotency_key=f"search_index:{object_type}:{int(object_id)}:{operation}",
    )


def enqueue_webhook(delivery_id: int):
    return create_job(
        "deliver_webhook",
        {"delivery_id": int(delivery_id)},
        priority=10,
        max_retries=5,
        idempotency_key=f"deliver_webhook:{int(delivery_id)}",
    )
