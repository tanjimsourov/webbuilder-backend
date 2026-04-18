"""Payment service layer.

This module provides basic Stripe integration points for checkout and
webhook processing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from payments.models import Invoice, Subscription, SubscriptionPlan

try:
    import stripe
except ImportError:  # pragma: no cover - dependency managed via requirements
    stripe = None

if stripe and settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def get_publishable_key() -> str:
    """Expose Stripe publishable key to frontend clients."""
    return settings.STRIPE_PUBLISHABLE_KEY or ""


def create_checkout_session(
    request: HttpRequest,
    plan: SubscriptionPlan,
    *,
    customer_email: str | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for a plan."""
    if not stripe:
        raise RuntimeError("Stripe SDK is not installed.")
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")

    success_url = request.build_absolute_uri(reverse("payments:success"))
    cancel_url = request.build_absolute_uri(reverse("payments:cancel"))
    mode = "subscription" if plan.stripe_price_id else "payment"
    if mode == "subscription":
        line_items = [{"price": plan.stripe_price_id, "quantity": 1}]
    else:
        line_items = [
            {
                "price_data": {
                    "currency": plan.currency.lower(),
                    "unit_amount": plan.amount,
                    "product_data": {
                        "name": plan.name,
                        "description": plan.description or "",
                    },
                },
                "quantity": 1,
            }
        ]

    session = stripe.checkout.Session.create(
        mode=mode,
        line_items=line_items,
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=customer_email,
        metadata=metadata or {"plan_id": str(plan.id)},
    )
    return {"id": session.get("id"), "url": session.get("url")}


def _upsert_subscription_from_stripe(payload: dict[str, Any]) -> Subscription | None:
    plan_id = payload.get("metadata", {}).get("plan_id")
    if not plan_id:
        return None
    try:
        plan = SubscriptionPlan.objects.get(pk=plan_id)
    except SubscriptionPlan.DoesNotExist:
        return None

    subscription, _ = Subscription.objects.update_or_create(
        stripe_subscription_id=payload.get("id", ""),
        defaults={
            "plan": plan,
            "status": payload.get("status", "active"),
            "current_period_end": datetime.fromtimestamp(payload.get("current_period_end", 0), tz=timezone.utc)
            if payload.get("current_period_end")
            else None,
        },
    )
    return subscription


def _upsert_invoice_from_stripe(payload: dict[str, Any]) -> Invoice:
    invoice, _ = Invoice.objects.update_or_create(
        stripe_invoice_id=payload.get("id"),
        defaults={
            "amount_due": payload.get("amount_due", 0),
            "currency": (payload.get("currency") or "usd").lower(),
            "paid": bool(payload.get("paid")),
            "issued_at": datetime.fromtimestamp(payload.get("created", 0), tz=timezone.utc)
            if payload.get("created")
            else datetime.now(timezone.utc),
            "invoice_number": payload.get("number", "") or "",
            "paid_at": datetime.fromtimestamp(payload.get("status_transitions", {}).get("paid_at"), tz=timezone.utc)
            if payload.get("status_transitions", {}).get("paid_at")
            else None,
        },
    )
    return invoice


def handle_webhook(event: dict[str, Any]) -> None:
    """Process Stripe webhook payloads."""
    event_type = event.get("type")
    payload = event.get("data", {}).get("object", {})
    if not event_type:
        return
    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        _upsert_subscription_from_stripe(payload)
    elif event_type in {"customer.subscription.deleted"}:
        stripe_subscription_id = payload.get("id")
        if stripe_subscription_id:
            Subscription.objects.filter(stripe_subscription_id=stripe_subscription_id).update(status="canceled")
    elif event_type in {"invoice.created", "invoice.paid", "invoice.payment_failed"}:
        _upsert_invoice_from_stripe(payload)
