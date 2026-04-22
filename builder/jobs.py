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

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import AutomationWebhookDelivery, Job, WebhookDelivery

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

    try:
        return Job.objects.create(
            job_type=job_type,
            job_id=job_id,
            payload=payload,
            scheduled_at=scheduled_at or timezone.now(),
            priority=priority,
            max_retries=max_retries,
        )
    except IntegrityError:
        return Job.objects.get(job_id=job_id)


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
            "publish_at": publish_at.isoformat(),
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
    delivery = WebhookDelivery.objects.create(
        webhook_id=webhook_id,
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


def queue_automation_webhook_delivery(
    webhook_id: int,
    event: str,
    payload: dict,
) -> AutomationWebhookDelivery:
    """Queue an automation webhook for delivery."""
    delivery = AutomationWebhookDelivery.objects.create(
        webhook_id=webhook_id,
        event=event,
        payload=payload,
        max_attempts=5,
        next_attempt_at=timezone.now(),
    )
    create_job(
        job_type="deliver_automation_webhook",
        payload={"delivery_id": delivery.id},
        priority=Job.PRIORITY_HIGH,
        idempotency_key=f"automation_webhook:{delivery.id}",
    )
    return delivery


def queue_search_index(
    object_type: str,
    object_id: int,
    *,
    operation: str = "upsert",
    priority: int = Job.PRIORITY_NORMAL,
) -> Job:
    """Queue a search indexing job for eventual consistency off the request path."""
    normalized_type = str(object_type or "").strip().lower()
    normalized_operation = str(operation or "upsert").strip().lower()
    dedupe_bucket = int(time.time() // 60)
    return create_job(
        job_type="search_index",
        payload={
            "object_type": normalized_type,
            "object_id": int(object_id),
            "operation": normalized_operation,
        },
        priority=priority,
        idempotency_key=f"{normalized_type}:{int(object_id)}:{normalized_operation}:{dedupe_bucket}",
    )


# ---------------------------------------------------------------------------
# Job Handlers
# ---------------------------------------------------------------------------

@register_job("publish_content")
def handle_publish_content(job: Job) -> dict:
    """Publish scheduled content."""
    from .models import Page, Post, Product

    def _ensure_aware(dt):
        if dt is None:
            return None
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def _job_publish_at():
        raw = job.payload.get("publish_at")
        if not raw:
            return None
        parsed = parse_datetime(str(raw))
        if parsed is None:
            return None
        return _ensure_aware(parsed)

    content_type = job.payload.get("content_type")
    content_id = job.payload.get("content_id")
    job_publish_at = _job_publish_at()

    if content_type == "page":
        from cms.services import publish_page_content

        try:
            page = Page.objects.select_related("site").get(pk=content_id)
        except Page.DoesNotExist:
            return {"error": f"page {content_id} not found"}
        page_scheduled_at = _ensure_aware(page.scheduled_at)

        # Protect against stale jobs when a page is rescheduled after the old job was created.
        if page_scheduled_at and job_publish_at:
            if abs((page_scheduled_at - job_publish_at).total_seconds()) > 1:
                return {
                    "skipped": True,
                    "reason": "Stale scheduled publish job",
                    "scheduled_at": page_scheduled_at.isoformat(),
                    "job_publish_at": job_publish_at.isoformat(),
                }

        if page_scheduled_at and page_scheduled_at > timezone.now():
            return {
                "skipped": True,
                "reason": "Scheduled time not reached",
                "scheduled_at": page_scheduled_at.isoformat(),
            }

        if page.status == Page.STATUS_PUBLISHED:
            return {"skipped": True, "reason": "Already published"}
        result = publish_page_content(page, actor="job_queue", reason="scheduled_publish")
        return {
            "published": True,
            "content_type": "page",
            "content_id": page.id,
            "revalidation_paths": result.get("routes", []),
        }

    model_map = {"post": Post, "product": Product}
    model = model_map.get(content_type)
    if not model:
        return {"error": f"Unknown content type: {content_type}"}

    try:
        content = model.objects.get(pk=content_id)
    except model.DoesNotExist:
        return {"error": f"{content_type} {content_id} not found"}

    content_scheduled_at = _ensure_aware(getattr(content, "scheduled_at", None))
    if content_scheduled_at and job_publish_at:
        if abs((content_scheduled_at - job_publish_at).total_seconds()) > 1:
            return {
                "skipped": True,
                "reason": "Stale scheduled publish job",
                "scheduled_at": content_scheduled_at.isoformat(),
                "job_publish_at": job_publish_at.isoformat(),
            }

    if content_scheduled_at and content_scheduled_at > timezone.now():
        return {
            "skipped": True,
            "reason": "Scheduled time not reached",
            "scheduled_at": content_scheduled_at.isoformat(),
        }

    if content.status == "published":
        return {"skipped": True, "reason": "Already published"}

    content.status = "published"
    content.published_at = timezone.now()
    content.save(update_fields=["status", "published_at", "updated_at"])

    from .services import trigger_webhooks

    event = f"{content_type}.published"
    trigger_webhooks(
        content.site,
        event,
        {
            f"{content_type}_id": content.id,
            "title": content.title,
            "slug": getattr(content, "slug", ""),
        },
    )

    return {"published": True, "content_type": content_type, "content_id": content_id}


@register_job("runtime_revalidate")
def handle_runtime_revalidate(job: Job) -> dict:
    """Run Next.js runtime revalidation for queued route payloads."""
    from cms.services import process_runtime_revalidation_job

    return process_runtime_revalidation_job(job.payload)


@register_job("search_index")
def handle_search_index(job: Job) -> dict:
    """Index or remove a document from Meilisearch."""
    from .models import MediaAsset, Page, Post, Product
    from shared.search.service import search_index

    object_type = str(job.payload.get("object_type") or "").strip().lower()
    operation = str(job.payload.get("operation") or "upsert").strip().lower()
    object_id = int(job.payload.get("object_id") or 0)
    if object_id <= 0:
        return {"error": "Invalid object_id"}

    if operation == "delete":
        index_map = {
            "page": "pages",
            "post": "posts",
            "product": "products",
            "media": "media",
        }
        index_name = index_map.get(object_type)
        if not index_name:
            return {"error": f"Unsupported object_type: {object_type}"}
        deleted = search_index.delete_document(index_name, f"{object_type}_{object_id}")
        return {"deleted": bool(deleted), "object_type": object_type, "object_id": object_id}

    if object_type == "page":
        page = Page.objects.select_related("site").filter(pk=object_id).first()
        if not page:
            return {"skipped": True, "reason": "missing", "object_type": object_type, "object_id": object_id}
        indexed = search_index.index_page(page)
        return {"indexed": bool(indexed), "object_type": object_type, "object_id": object_id}

    if object_type == "post":
        post = (
            Post.objects.select_related("site")
            .prefetch_related("categories", "tags")
            .filter(pk=object_id)
            .first()
        )
        if not post:
            return {"skipped": True, "reason": "missing", "object_type": object_type, "object_id": object_id}
        indexed = search_index.index_post(post)
        return {"indexed": bool(indexed), "object_type": object_type, "object_id": object_id}

    if object_type == "product":
        product = (
            Product.objects.select_related("site")
            .prefetch_related("categories", "variants")
            .filter(pk=object_id)
            .first()
        )
        if not product:
            return {"skipped": True, "reason": "missing", "object_type": object_type, "object_id": object_id}
        indexed = search_index.index_product(product)
        return {"indexed": bool(indexed), "object_type": object_type, "object_id": object_id}

    if object_type == "media":
        media = MediaAsset.objects.select_related("site").filter(pk=object_id).first()
        if not media:
            return {"skipped": True, "reason": "missing", "object_type": object_type, "object_id": object_id}
        indexed = search_index.index_media(media)
        return {"indexed": bool(indexed), "object_type": object_type, "object_id": object_id}

    return {"error": f"Unsupported object_type: {object_type}"}


@register_job("ai_generate")
def handle_ai_generate(job: Job) -> dict:
    """Run an AI generation job and persist usage/output metadata."""
    from provider.models import AIJob
    from shared.ai.service import process_ai_job

    ai_job_id = int(job.payload.get("ai_job_id") or 0)
    if ai_job_id <= 0:
        return {"error": "Invalid ai_job_id"}
    try:
        ai_job = AIJob.objects.select_related("site").get(pk=ai_job_id)
    except AIJob.DoesNotExist:
        return {"error": f"AI job {ai_job_id} not found"}

    processed = process_ai_job(ai_job)
    return {
        "ai_job_id": processed.id,
        "status": processed.status,
        "provider": processed.provider,
        "model_name": processed.model_name,
        "total_tokens": processed.total_tokens,
    }


@register_job("deliver_notification_email")
def handle_deliver_notification_email(job: Job) -> dict:
    """Deliver a queued email notification."""
    from provider.services import providers
    from notifications.models import Notification

    notification_id = int(job.payload.get("notification_id") or 0)
    if notification_id <= 0:
        return {"error": "Invalid notification_id"}

    try:
        notification = Notification.objects.select_related("recipient").get(pk=notification_id)
    except Notification.DoesNotExist:
        return {"error": f"Notification {notification_id} not found"}

    if notification.channel != Notification.CHANNEL_EMAIL:
        return {"skipped": True, "reason": "notification.channel_mismatch"}
    if notification.status in {Notification.STATUS_SENT, Notification.STATUS_READ}:
        return {"skipped": True, "reason": "notification.already_delivered"}
    recipient_email = ""
    if notification.recipient_id and notification.recipient.email:
        recipient_email = notification.recipient.email
    else:
        recipient_email = str((notification.payload or {}).get("recipient_email") or "").strip()
    if not recipient_email:
        notification.status = Notification.STATUS_FAILED
        notification.error_message = "Recipient email unavailable."
        notification.save(update_fields=["status", "error_message", "updated_at"])
        return {"error": "Recipient email unavailable."}

    try:
        providers.email.send(
            subject=notification.subject or "Notification",
            body=notification.body or "",
            to=[recipient_email],
            html="",
        )
        notification.status = Notification.STATUS_SENT
        notification.delivered_at = timezone.now()
        notification.error_message = ""
        notification.save(update_fields=["status", "delivered_at", "error_message", "updated_at"])
        return {"notification_id": notification.id, "delivered": True}
    except Exception as exc:
        notification.status = Notification.STATUS_FAILED
        notification.error_message = str(exc)[:2000]
        notification.save(update_fields=["status", "error_message", "updated_at"])
        return {"notification_id": notification.id, "delivered": False, "error": notification.error_message}


@register_job("deliver_integration_webhook")
def handle_deliver_integration_webhook(job: Job) -> dict:
    """Deliver one integration webhook endpoint payload with retries."""
    from urllib import error as urllib_error
    from urllib import request as urllib_request

    from notifications.models import WebhookEndpointDelivery
    from shared.events.signing import sign_payload

    delivery_id = int(job.payload.get("delivery_id") or 0)
    if delivery_id <= 0:
        return {"error": "Invalid delivery_id"}

    lock_key = f"integration_webhook_delivery_lock:{delivery_id}"
    if not cache.add(lock_key, True, timeout=120):
        return {"skipped": True, "reason": "Delivery is already being processed"}

    try:
        delivery = WebhookEndpointDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    except WebhookEndpointDelivery.DoesNotExist:
        cache.delete(lock_key)
        return {"error": f"Delivery {delivery_id} not found"}

    endpoint = delivery.endpoint
    try:
        if delivery.status == WebhookEndpointDelivery.STATUS_DELIVERED:
            return {"skipped": True, "reason": "Already delivered"}

        delivery.attempt_count += 1
        delivery.last_attempt_at = timezone.now()

        payload_bytes = json.dumps(delivery.payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WebsiteBuilder-IntegrationWebhook/1.0",
            "X-Webhook-Event": delivery.event,
            "X-Webhook-Delivery": str(delivery.id),
        }
        if isinstance(endpoint.headers, dict):
            for key, value in endpoint.headers.items():
                key_text = str(key).strip()
                if key_text:
                    headers[key_text] = str(value)
        if endpoint.signing_secret:
            headers["X-Webhook-Signature"] = sign_payload(endpoint.signing_secret, payload_bytes)

        req = urllib_request.Request(
            endpoint.url,
            data=payload_bytes,
            headers=headers,
            method="POST",
        )
        start_time = time.time()
        status_code = 0
        response_text = ""
        try:
            with urllib_request.urlopen(req, timeout=max(1, int(endpoint.timeout_seconds or 15))) as response:
                status_code = int(response.status)
                response_text = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            status_code = int(exc.code)
            response_text = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.time() - start_time) * 1000)

        delivery.response_status = status_code
        delivery.response_body = response_text[:5000]
        delivery.response_time_ms = elapsed_ms

        if 200 <= status_code < 300:
            delivery.status = WebhookEndpointDelivery.STATUS_DELIVERED
            delivery.error_message = ""
        else:
            raise RuntimeError(f"HTTP {status_code}: {response_text[:200]}")
    except Exception as exc:
        delivery.error_message = str(exc)[:2000]
        if delivery.attempt_count < delivery.max_attempts:
            delay_minutes = 5 ** (delivery.attempt_count - 1)
            delivery.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)
            create_job(
                job_type="deliver_integration_webhook",
                payload={"delivery_id": delivery.id},
                scheduled_at=delivery.next_attempt_at,
                priority=Job.PRIORITY_NORMAL,
                idempotency_key=f"integration_webhook_retry:{delivery.id}:{delivery.attempt_count}",
            )
        else:
            delivery.status = WebhookEndpointDelivery.STATUS_FAILED
    finally:
        delivery.save()
        cache.delete(lock_key)

    return {
        "delivery_id": delivery.id,
        "status": delivery.status,
        "attempt": delivery.attempt_count,
        "status_code": delivery.response_status,
    }


@register_job("compliance_export_data")
def handle_compliance_export_data(job: Job) -> dict:
    """Build a data export payload for a requested user."""
    from core.compliance import process_data_export_job
    from core.models import DataExportJob

    export_job_id = int(job.payload.get("export_job_id") or 0)
    if export_job_id <= 0:
        return {"error": "Invalid export_job_id"}
    try:
        export_job = DataExportJob.objects.get(pk=export_job_id)
    except DataExportJob.DoesNotExist:
        return {"error": f"DataExportJob {export_job_id} not found"}
    processed = process_data_export_job(export_job)
    return {"export_job_id": processed.id, "status": processed.status}


@register_job("compliance_delete_data")
def handle_compliance_delete_data(job: Job) -> dict:
    """Execute approved account deletion/anonymization workflow."""
    from core.compliance import process_data_deletion_job
    from core.models import DataDeletionJob

    deletion_job_id = int(job.payload.get("deletion_job_id") or 0)
    if deletion_job_id <= 0:
        return {"error": "Invalid deletion_job_id"}
    try:
        deletion_job = DataDeletionJob.objects.get(pk=deletion_job_id)
    except DataDeletionJob.DoesNotExist:
        return {"error": f"DataDeletionJob {deletion_job_id} not found"}
    processed = process_data_deletion_job(deletion_job)
    return {"deletion_job_id": processed.id, "status": processed.status}


@register_job("deliver_webhook")
def handle_deliver_webhook(job: Job) -> dict:
    """Deliver a webhook."""
    from urllib import error as urllib_error
    from urllib import request as urllib_request

    delivery_id = job.payload.get("delivery_id")
    if not delivery_id:
        return {"error": "No delivery_id in payload"}

    lock_key = f"webhook_delivery_lock:{delivery_id}"
    if not cache.add(lock_key, True, timeout=120):
        return {"skipped": True, "reason": "Delivery is already being processed"}

    try:
        delivery = WebhookDelivery.objects.select_related("webhook").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        cache.delete(lock_key)
        return {"error": f"Delivery {delivery_id} not found"}

    webhook = delivery.webhook

    try:
        if delivery.status == WebhookDelivery.STATUS_DELIVERED:
            return {"skipped": True, "reason": "Already delivered"}

        delivery.attempt_count += 1
        delivery.last_attempt_at = timezone.now()

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
        body = json.dumps(delivery.payload).encode("utf-8")
        req = urllib_request.Request(
            webhook.url,
            data=body,
            headers=headers,
            method="POST",
        )
        status_code = 0
        response_text = ""
        try:
            with urllib_request.urlopen(req, timeout=30) as response:
                status_code = int(response.status)
                response_text = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            status_code = int(exc.code)
            response_text = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.time() - start_time) * 1000)

        delivery.response_status = status_code
        delivery.response_body = response_text[:5000]
        delivery.response_time_ms = elapsed_ms

        if 200 <= status_code < 300:
            delivery.status = WebhookDelivery.STATUS_DELIVERED
            webhook.success_count += 1
            webhook.last_triggered_at = timezone.now()
            webhook.save(update_fields=["success_count", "last_triggered_at", "updated_at"])
        else:
            raise RuntimeError(f"HTTP {status_code}: {response_text[:200]}")

    except Exception as e:
        delivery.error_message = str(e)
        webhook.failure_count += 1
        webhook.save(update_fields=["failure_count", "updated_at"])

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
    finally:
        delivery.save()
        cache.delete(lock_key)

    return {
        "delivered": delivery.status == WebhookDelivery.STATUS_DELIVERED,
        "attempt": delivery.attempt_count,
        "status_code": delivery.response_status,
    }


@register_job("deliver_automation_webhook")
def handle_deliver_automation_webhook(job: Job) -> dict:
    """Deliver an automation webhook with retry support."""
    from urllib import error as urllib_error
    from urllib import request as urllib_request

    delivery_id = job.payload.get("delivery_id")
    if not delivery_id:
        return {"error": "No delivery_id in payload"}

    lock_key = f"automation_webhook_delivery_lock:{delivery_id}"
    if not cache.add(lock_key, True, timeout=120):
        return {"skipped": True, "reason": "Delivery is already being processed"}

    try:
        delivery = AutomationWebhookDelivery.objects.select_related("webhook").get(pk=delivery_id)
    except AutomationWebhookDelivery.DoesNotExist:
        cache.delete(lock_key)
        return {"error": f"Automation delivery {delivery_id} not found"}

    webhook = delivery.webhook
    try:
        if delivery.status == AutomationWebhookDelivery.STATUS_DELIVERED:
            return {"skipped": True, "reason": "Already delivered"}
        delivery.attempt_count += 1
        delivery.last_attempt_at = timezone.now()

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "WebsiteBuilder-Automation/1.0",
            "X-Automation-Event": delivery.event,
            "X-Automation-Delivery": str(delivery.id),
        }
        if isinstance(webhook.headers, dict):
            for key, value in webhook.headers.items():
                key_text = str(key).strip()
                value_text = str(value)
                if key_text:
                    headers[key_text] = value_text
        if webhook.secret:
            import hmac

            signature = hmac.new(
                webhook.secret.encode(),
                json.dumps(delivery.payload).encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["X-Automation-Signature"] = f"sha256={signature}"

        start_time = time.time()
        body = json.dumps(delivery.payload).encode("utf-8")
        req = urllib_request.Request(
            webhook.url,
            data=body,
            headers=headers,
            method="POST",
        )
        status_code = 0
        response_text = ""
        try:
            with urllib_request.urlopen(req, timeout=max(1, int(webhook.timeout_seconds or 15))) as response:
                status_code = int(response.status)
                response_text = response.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            status_code = int(exc.code)
            response_text = exc.read().decode("utf-8", errors="replace")
        elapsed_ms = int((time.time() - start_time) * 1000)

        delivery.response_status = status_code
        delivery.response_body = response_text[:5000]
        delivery.response_time_ms = elapsed_ms

        if 200 <= status_code < 300:
            delivery.status = AutomationWebhookDelivery.STATUS_DELIVERED
        else:
            raise RuntimeError(f"HTTP {status_code}: {response_text[:200]}")
    except Exception as exc:
        delivery.error_message = str(exc)
        if delivery.attempt_count < delivery.max_attempts:
            delay_minutes = 5 ** (delivery.attempt_count - 1)
            delivery.next_attempt_at = timezone.now() + timedelta(minutes=delay_minutes)
            create_job(
                job_type="deliver_automation_webhook",
                payload={"delivery_id": delivery.id},
                scheduled_at=delivery.next_attempt_at,
                priority=Job.PRIORITY_NORMAL,
                idempotency_key=f"automation_webhook_retry:{delivery.id}:{delivery.attempt_count}",
            )
        else:
            delivery.status = AutomationWebhookDelivery.STATUS_FAILED
    finally:
        delivery.save()
        cache.delete(lock_key)

    return {
        "delivered": delivery.status == AutomationWebhookDelivery.STATUS_DELIVERED,
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

def _claim_pending_jobs(batch_size: int) -> list[Job]:
    """Claim pending jobs using row-level locks to prevent duplicate workers."""
    now = timezone.now()
    with transaction.atomic():
        queryset = (
            Job.objects.filter(status=Job.STATUS_PENDING, scheduled_at__lte=now)
            .order_by("-priority", "scheduled_at", "id")
        )
        if connection.features.has_select_for_update:
            select_kwargs: dict[str, bool] = {}
            if connection.features.has_select_for_update_skip_locked:
                select_kwargs["skip_locked"] = True
            queryset = queryset.select_for_update(**select_kwargs)
        jobs = list(queryset[:batch_size])
        if not jobs:
            return []
        claim_time = timezone.now()
        for job in jobs:
            job.status = Job.STATUS_RUNNING
            job.started_at = claim_time
            job.updated_at = claim_time
        Job.objects.bulk_update(jobs, ["status", "started_at", "updated_at"])
    return jobs


def process_pending_jobs(batch_size: int = 10) -> int:
    """Process pending jobs that are due."""
    jobs = _claim_pending_jobs(batch_size=batch_size)

    processed = 0

    for job in jobs:
        try:
            process_job(job, already_running=True)
            processed += 1
        except Exception:
            logger.exception("Unhandled error processing claimed job %s", job.job_id)
            Job.objects.filter(pk=job.pk).update(
                status=Job.STATUS_FAILED,
                completed_at=timezone.now(),
                last_error="Unhandled processor exception.",
            )

    return processed


def process_job(job: Job, *, already_running: bool = False) -> None:
    """Process a single job."""
    handler = get_job_handler(job.job_type)
    if not handler:
        job.status = Job.STATUS_FAILED
        job.last_error = f"No handler for job type: {job.job_type}"
        job.save(update_fields=["status", "last_error", "updated_at"])
        return

    if not already_running:
        # Mark as running
        job.status = Job.STATUS_RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])

    try:
        result = handler(job)
        job.result = result or {}
        job.status = Job.STATUS_COMPLETED
        job.completed_at = timezone.now()
        if job.job_type == "publish_content":
            content_type = str((job.result or {}).get("content_type") or job.payload.get("content_type") or "")
            content_id = int((job.result or {}).get("content_id") or job.payload.get("content_id") or 0)
            if content_type and content_id > 0:
                site = None
                if content_type == "page":
                    from .models import Page

                    site = Page.objects.filter(pk=content_id).select_related("site").values_list("site_id", flat=True).first()
                elif content_type == "post":
                    from .models import Post

                    site = Post.objects.filter(pk=content_id).select_related("site").values_list("site_id", flat=True).first()
                elif content_type == "product":
                    from .models import Product

                    site = Product.objects.filter(pk=content_id).select_related("site").values_list("site_id", flat=True).first()
                if site:
                    from .models import Site
                    from notifications.services import trigger_webhooks

                    site_obj = Site.objects.filter(pk=site).first()
                    if site_obj:
                        trigger_webhooks(
                            site_obj,
                            "publish.job.completed",
                            {
                                "job_id": job.job_id,
                                "content_type": content_type,
                                "content_id": content_id,
                                "result": job.result,
                            },
                        )

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
        status__in=[Post.STATUS_DRAFT, Post.STATUS_SCHEDULED],
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
