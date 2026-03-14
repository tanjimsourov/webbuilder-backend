"""
Background Jobs System

Provides a lightweight job queue for:
- Scheduled publishing of pages/posts/products
- Webhook delivery with retry logic
- Periodic tasks (SEO audits, etc.)

This implementation uses Django's database as a job store and can be run
via a management command or cron job. For production at scale, consider
migrating to Celery or Django-RQ.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import traceback
from datetime import timedelta
from typing import Any, Callable

from django.utils import timezone

from .models import Job, WebhookDelivery

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job Registry
# ---------------------------------------------------------------------------

_job_handlers: dict[str, Callable] = {}


def register_job(job_type: str):
    """Decorator to register a job handler."""
    def decorator(func: Callable):
        _job_handlers[job_type] = func
        return func
    return decorator


def get_job_handler(job_type: str) -> Callable | None:
    """Get the handler for a job type."""
    return _job_handlers.get(job_type)


# ---------------------------------------------------------------------------
# Job Creation
# ---------------------------------------------------------------------------

def create_job(
    job_type: str,
    payload: dict,
    scheduled_at: timezone.datetime = None,
    priority: int = Job.PRIORITY_NORMAL,
    max_retries: int = 3,
    idempotency_key: str = None,
) -> Job:
    """Create a new job."""
    if idempotency_key:
        job_id = hashlib.sha256(f"{job_type}:{idempotency_key}".encode()).hexdigest()[:32]
    else:
        job_id = hashlib.sha256(f"{job_type}:{time.time()}:{json.dumps(payload, sort_keys=True)}".encode()).hexdigest()[:32]

    # Check for existing job with same ID
    existing = Job.objects.filter(job_id=job_id).first()
    if existing:
        return existing

    return Job.objects.create(
        job_type=job_type,
        job_id=job_id,
        payload=payload,
        scheduled_at=scheduled_at or timezone.now(),
        priority=priority,
        max_retries=max_retries,
    )


def schedule_publish(
    content_type: str,
    content_id: int,
    publish_at: timezone.datetime,
) -> Job:
    """Schedule content for publishing."""
    return create_job(
        job_type="publish_content",
        payload={
            "content_type": content_type,
            "content_id": content_id,
        },
        scheduled_at=publish_at,
        idempotency_key=f"{content_type}:{content_id}:{publish_at.isoformat()}",
    )


def queue_webhook_delivery(
    webhook_id: int,
    event: str,
    payload: dict,
) -> WebhookDelivery:
    """Queue a webhook for delivery."""
    from .models import Webhook

    webhook = Webhook.objects.get(pk=webhook_id)

    delivery = WebhookDelivery.objects.create(
        webhook=webhook,
        event=event,
        payload=payload,
        next_attempt_at=timezone.now(),
    )

    # Also create a job for processing
    create_job(
        job_type="deliver_webhook",
        payload={"delivery_id": delivery.id},
        priority=Job.PRIORITY_HIGH,
        idempotency_key=f"webhook:{delivery.id}",
    )

    return delivery


# ---------------------------------------------------------------------------
# Job Handlers
# ---------------------------------------------------------------------------

@register_job("publish_content")
def handle_publish_content(job: Job) -> dict:
    """Publish scheduled content."""
    from .models import Page, Post, Product

    content_type = job.payload.get("content_type")
    content_id = job.payload.get("content_id")

    model_map = {
        "page": Page,
        "post": Post,
        "product": Product,
    }

    model = model_map.get(content_type)
    if not model:
        return {"error": f"Unknown content type: {content_type}"}

    try:
        content = model.objects.get(pk=content_id)
    except model.DoesNotExist:
        return {"error": f"{content_type} {content_id} not found"}

    # Check if already published
    if content.status == "published":
        return {"skipped": True, "reason": "Already published"}

    # Publish
    content.status = "published"
    content.published_at = timezone.now()
    content.save(update_fields=["status", "published_at", "updated_at"])

    # Trigger webhook
    from .services import trigger_webhooks
    event = f"{content_type}.published"
    trigger_webhooks(content.site, event, {
        f"{content_type}_id": content.id,
        "title": content.title,
        "slug": getattr(content, "slug", ""),
    })

    return {"published": True, "content_type": content_type, "content_id": content_id}


@register_job("deliver_webhook")
def handle_deliver_webhook(job: Job) -> dict:
    """Deliver a webhook."""
    import requests

    delivery_id = job.payload.get("delivery_id")
    if not delivery_id:
        return {"error": "No delivery_id in payload"}

    try:
        delivery = WebhookDelivery.objects.select_related("webhook").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return {"error": f"Delivery {delivery_id} not found"}

    if delivery.status == WebhookDelivery.STATUS_DELIVERED:
        return {"skipped": True, "reason": "Already delivered"}

    webhook = delivery.webhook
    delivery.attempt_count += 1
    delivery.last_attempt_at = timezone.now()

    try:
        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WebsiteBuilder-Webhook/1.0",
            "X-Webhook-Event": delivery.event,
            "X-Webhook-Delivery": str(delivery.id),
        }

        # Add signature if secret is configured
        if webhook.secret:
            import hmac
            signature = hmac.new(
                webhook.secret.encode(),
                json.dumps(delivery.payload).encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"

        # Send request
        start_time = time.time()
        response = requests.post(
            webhook.url,
            json=delivery.payload,
            headers=headers,
            timeout=30,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        delivery.response_status = response.status_code
        delivery.response_body = response.text[:5000]  # Limit stored response
        delivery.response_time_ms = elapsed_ms

        if 200 <= response.status_code < 300:
            delivery.status = WebhookDelivery.STATUS_DELIVERED
            webhook.success_count += 1
            webhook.last_triggered_at = timezone.now()
            webhook.save(update_fields=["success_count", "last_triggered_at"])
        else:
            raise Exception(f"HTTP {response.status_code}: {response.text[:200]}")

    except Exception as e:
        delivery.error_message = str(e)
        webhook.failure_count += 1
        webhook.save(update_fields=["failure_count"])

        # Schedule retry if attempts remaining
        if delivery.attempt_count < delivery.max_attempts:
            # Exponential backoff: 1min, 5min, 25min, 2hr, 10hr
            delay_minutes = 5 ** (delivery.attempt_count - 1)
            delivery.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)

            # Create retry job with idempotency key to prevent duplicates
            create_job(
                job_type="deliver_webhook",
                payload={"delivery_id": delivery.id},
                scheduled_at=delivery.next_attempt_at,
                priority=Job.PRIORITY_NORMAL,
                idempotency_key=f"webhook_retry:{delivery.id}:{delivery.attempt_count}",
            )
        else:
            delivery.status = WebhookDelivery.STATUS_FAILED

    delivery.save()

    return {
        "delivered": delivery.status == WebhookDelivery.STATUS_DELIVERED,
        "attempt": delivery.attempt_count,
        "status_code": delivery.response_status,
    }


@register_job("run_seo_audit")
def handle_run_seo_audit(job: Job) -> dict:
    """Run SEO audit for a page."""
    from .models import Page
    from .seo_services import run_page_audit

    page_id = job.payload.get("page_id")
    base_url = job.payload.get("base_url", "http://127.0.0.1:8000")

    try:
        page = Page.objects.get(pk=page_id)
    except Page.DoesNotExist:
        return {"error": f"Page {page_id} not found"}

    audit = run_page_audit(page, base_url)

    return {
        "audit_id": audit.id,
        "score": audit.score,
        "status": audit.status,
    }


# ---------------------------------------------------------------------------
# Job Runner
# ---------------------------------------------------------------------------

def process_pending_jobs(batch_size: int = 10) -> int:
    """Process pending jobs that are due."""
    now = timezone.now()

    # Get jobs that are ready to run
    jobs = Job.objects.filter(
        status=Job.STATUS_PENDING,
        scheduled_at__lte=now,
    ).order_by("-priority", "scheduled_at")[:batch_size]

    processed = 0

    for job in jobs:
        try:
            process_job(job)
            processed += 1
        except Exception as e:
            logger.error(f"Error processing job {job.job_id}: {e}")

    return processed


def process_job(job: Job) -> None:
    """Process a single job."""
    handler = get_job_handler(job.job_type)
    if not handler:
        job.status = Job.STATUS_FAILED
        job.last_error = f"No handler for job type: {job.job_type}"
        job.save(update_fields=["status", "last_error", "updated_at"])
        return

    # Mark as running
    job.status = Job.STATUS_RUNNING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        result = handler(job)
        job.result = result or {}
        job.status = Job.STATUS_COMPLETED
        job.completed_at = timezone.now()

    except Exception as e:
        job.last_error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        job.retry_count += 1

        if job.retry_count < job.max_retries:
            # Schedule retry
            job.status = Job.STATUS_PENDING
            job.scheduled_at = timezone.now() + timedelta(seconds=job.retry_delay_seconds * job.retry_count)
        else:
            job.status = Job.STATUS_FAILED
            job.completed_at = timezone.now()

    job.save()


def cleanup_old_jobs(days: int = 30) -> int:
    """Delete completed/failed jobs older than specified days."""
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = Job.objects.filter(
        status__in=[Job.STATUS_COMPLETED, Job.STATUS_FAILED, Job.STATUS_CANCELLED],
        updated_at__lt=cutoff,
    ).delete()
    return deleted


def schedule_content_publish(content_type: str, content_id: int, scheduled_at) -> Job:
    """Schedule content for future publishing."""
    return create_job(
        job_type="publish_content",
        payload={"content_type": content_type, "content_id": content_id},
        scheduled_at=scheduled_at,
        priority=Job.PRIORITY_NORMAL,
        idempotency_key=f"publish:{content_type}:{content_id}",
    )


def process_scheduled_content() -> int:
    """Find and queue all content that should be published now."""
    from .models import Page, Post, Product

    now = timezone.now()
    queued = 0

    # Pages
    pages = Page.objects.filter(
        status=Page.STATUS_DRAFT,
        scheduled_at__isnull=False,
        scheduled_at__lte=now,
    )
    for page in pages:
        schedule_content_publish("page", page.id, now)
        queued += 1

    # Posts
    posts = Post.objects.filter(
        status=Post.STATUS_DRAFT,
        scheduled_at__isnull=False,
        scheduled_at__lte=now,
    )
    for post in posts:
        schedule_content_publish("post", post.id, now)
        queued += 1

    # Products
    products = Product.objects.filter(
        status=Product.STATUS_DRAFT,
        scheduled_at__isnull=False,
        scheduled_at__lte=now,
    )
    for product in products:
        schedule_content_publish("product", product.id, now)
        queued += 1

    return queued
