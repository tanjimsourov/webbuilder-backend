"""Commerce domain services."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from builder.commerce_runtime import calculate_cart_pricing as runtime_calculate_cart_pricing
from provider.services import providers
from shared.http.context import get_request_id
from shared.payments.service import payment_gateway
from shared.seo import build_seo_payload

from .models import (
    Cart,
    CartItem,
    CheckoutSession,
    CommerceEvent,
    Customer,
    DiscountCode,
    FraudSignal,
    Inventory,
    Order,
    OrderAuditLog,
    OrderItem,
    Payment,
    Product,
    ProductVariant,
    Refund,
    StockReservation,
    TaxRecord,
)

logger = logging.getLogger(__name__)


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_variant(product: Product, variant_id: int | None = None) -> ProductVariant:
    variants = product.variants.filter(is_active=True)
    if variant_id:
        return variants.get(pk=variant_id)
    variant = variants.order_by("-is_default", "title").first()
    if variant is None:
        raise ProductVariant.DoesNotExist("No active variant is available for this product.")
    return variant


def _inventory_record_for_variant(variant: ProductVariant) -> Inventory:
    inventory, created = Inventory.objects.get_or_create(
        variant=variant,
        defaults={
            "on_hand": variant.inventory,
            "reserved": 0,
            "low_stock_threshold": variant.low_stock_threshold,
        },
    )
    if created:
        variant.inventory = inventory.on_hand
        variant.inventory_state = variant.refresh_inventory_state()
        variant.save(update_fields=["inventory", "inventory_state", "updated_at"])
    return inventory


def _sync_variant_from_inventory(variant: ProductVariant, inventory: Inventory) -> None:
    variant.inventory = inventory.on_hand
    variant.low_stock_threshold = inventory.low_stock_threshold
    variant.inventory_state = variant.refresh_inventory_state()
    variant.save(update_fields=["inventory", "low_stock_threshold", "inventory_state", "updated_at"])


def ensure_variant_inventory(variant: ProductVariant, quantity: int) -> None:
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    if not variant.track_inventory:
        return
    inventory = _inventory_record_for_variant(variant)
    if inventory.available >= quantity:
        return
    if variant.allow_backorder:
        return
    raise ValueError(f"Only {inventory.available} units are available for {variant.title}.")


def sync_cart_item(cart_item: CartItem) -> CartItem:
    variant = cart_item.product_variant
    cart_item.unit_price = quantize_money(variant.price)
    cart_item.line_total = quantize_money(variant.price * cart_item.quantity)
    return cart_item


def recalculate_cart(cart: Cart) -> Cart:
    subtotal = Decimal("0.00")
    for item in cart.items.select_related("product_variant").all():
        sync_cart_item(item)
        item.save(update_fields=["unit_price", "line_total", "updated_at"])
        subtotal += item.line_total

    cart.subtotal = quantize_money(subtotal)
    cart.total = quantize_money(subtotal)
    cart.save(update_fields=["subtotal", "total", "updated_at"])
    return cart


def get_or_create_cart(site, session, *, customer: Customer | None = None) -> Cart:
    if not session.session_key:
        session.create()

    expiry_hours = int(getattr(settings, "COMMERCE_CART_EXPIRY_HOURS", 72) or 72)
    cart, _ = Cart.objects.get_or_create(
        site=site,
        session_key=session.session_key,
        status=Cart.STATUS_OPEN,
        defaults={
            "currency": "USD",
            "customer": customer,
            "expires_at": timezone.now() + timedelta(hours=max(1, expiry_hours)),
        },
    )
    if customer and not cart.customer_id:
        cart.customer = customer
        cart.save(update_fields=["customer", "updated_at"])
    return recalculate_cart(cart)


def calculate_pricing(
    cart: Cart,
    *,
    shipping_address: dict | None = None,
    shipping_rate_id: int | None = None,
    discount_code: str | None = None,
) -> dict:
    pricing = runtime_calculate_cart_pricing(
        cart,
        shipping_address=shipping_address or {},
        shipping_rate_id=shipping_rate_id,
        discount_code=discount_code,
    )
    pricing["subtotal"] = quantize_money(pricing["subtotal"])
    pricing["shipping_total"] = quantize_money(pricing["shipping_total"])
    pricing["shipping_original_total"] = quantize_money(pricing["shipping_original_total"])
    pricing["tax_total"] = quantize_money(pricing["tax_total"])
    pricing["discount_total"] = quantize_money(pricing["discount_total"])
    pricing["total"] = quantize_money(pricing["total"])
    return pricing


def _reserve_inventory_for_checkout(checkout: CheckoutSession) -> None:
    cart_items = list(checkout.cart.items.select_related("product_variant").all())
    for item in cart_items:
        variant = ProductVariant.objects.select_for_update().get(pk=item.product_variant_id)
        if not variant.track_inventory:
            continue
        inventory = Inventory.objects.select_for_update().get_or_create(
            variant=variant,
            defaults={
                "on_hand": variant.inventory,
                "reserved": 0,
                "low_stock_threshold": variant.low_stock_threshold,
            },
        )[0]
        if not variant.allow_backorder and inventory.available < item.quantity:
            raise ValueError(f"Not enough stock for {variant.title}.")
        reservation = StockReservation.objects.filter(
            checkout_session=checkout,
            product_variant=variant,
            status=StockReservation.STATUS_RESERVED,
        ).first()
        previous_quantity = reservation.quantity if reservation else 0
        delta = item.quantity - previous_quantity
        if delta > 0:
            inventory.reserved = F("reserved") + delta
            inventory.save(update_fields=["reserved", "updated_at"])
            inventory.refresh_from_db(fields=["reserved"])
        elif delta < 0:
            inventory.reserved = max(0, inventory.reserved + delta)
            inventory.save(update_fields=["reserved", "updated_at"])
        if reservation:
            reservation.quantity = item.quantity
            reservation.expires_at = checkout.expires_at
            reservation.save(update_fields=["quantity", "expires_at", "updated_at"])
        else:
            StockReservation.objects.create(
                site=checkout.site,
                product_variant=variant,
                cart=checkout.cart,
                checkout_session=checkout,
                quantity=item.quantity,
                status=StockReservation.STATUS_RESERVED,
                expires_at=checkout.expires_at,
            )
        _sync_variant_from_inventory(variant, inventory)


def _release_checkout_reservations(checkout: CheckoutSession, *, mark_status: str) -> None:
    reservations = list(
        StockReservation.objects.select_for_update()
        .filter(checkout_session=checkout, status=StockReservation.STATUS_RESERVED)
        .select_related("product_variant")
    )
    for reservation in reservations:
        variant = reservation.product_variant
        if variant.track_inventory:
            inventory = Inventory.objects.select_for_update().get_or_create(
                variant=variant,
                defaults={
                    "on_hand": variant.inventory,
                    "reserved": 0,
                    "low_stock_threshold": variant.low_stock_threshold,
                },
            )[0]
            inventory.reserved = max(0, inventory.reserved - reservation.quantity)
            inventory.save(update_fields=["reserved", "updated_at"])
            _sync_variant_from_inventory(variant, inventory)
        reservation.status = mark_status
        reservation.save(update_fields=["status", "updated_at"])


def _commit_checkout_reservations(checkout: CheckoutSession, order: Order) -> None:
    reservations = list(
        StockReservation.objects.select_for_update()
        .filter(checkout_session=checkout, status=StockReservation.STATUS_RESERVED)
        .select_related("product_variant")
    )
    for reservation in reservations:
        variant = reservation.product_variant
        if variant.track_inventory:
            inventory = Inventory.objects.select_for_update().get_or_create(
                variant=variant,
                defaults={
                    "on_hand": variant.inventory,
                    "reserved": 0,
                    "low_stock_threshold": variant.low_stock_threshold,
                },
            )[0]
            inventory.reserved = max(0, inventory.reserved - reservation.quantity)
            if not variant.allow_backorder:
                inventory.on_hand = max(0, inventory.on_hand - reservation.quantity)
            else:
                inventory.on_hand = inventory.on_hand - reservation.quantity
            inventory.save(update_fields=["reserved", "on_hand", "updated_at"])
            _sync_variant_from_inventory(variant, inventory)
        reservation.order = order
        reservation.status = StockReservation.STATUS_COMMITTED
        reservation.save(update_fields=["order", "status", "updated_at"])


def _build_order_number(site_id: int) -> str:
    date_part = timezone.now().strftime("%Y%m%d")
    return f"WB-{site_id}-{date_part}-{uuid4().hex[:8].upper()}"


def build_order_number(site_id: int) -> str:
    for _ in range(10):
        value = _build_order_number(site_id)
        if not Order.objects.filter(order_number=value).exists():
            return value
    return _build_order_number(site_id)


def _upsert_customer(
    *,
    site,
    customer_email: str,
    customer_name: str,
    customer_phone: str = "",
    newsletter_consent: bool = False,
    user=None,
) -> tuple[Customer, bool]:
    normalized_email = (customer_email or "").strip().lower()
    first_name = ""
    last_name = ""
    if customer_name.strip():
        parts = customer_name.strip().split()
        first_name = parts[0]
        if len(parts) > 1:
            last_name = " ".join(parts[1:])
    customer, created = Customer.objects.update_or_create(
        site=site,
        email=normalized_email,
        defaults={
            "user": user if getattr(user, "is_authenticated", False) else None,
            "first_name": first_name,
            "last_name": last_name,
            "phone": customer_phone[:40],
            "newsletter_consent": newsletter_consent,
        },
    )
    return customer, created


def log_order_audit(
    order: Order,
    *,
    action: str,
    actor=None,
    message: str = "",
    metadata: dict | None = None,
) -> OrderAuditLog:
    return OrderAuditLog.objects.create(
        order=order,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        message=message[:280],
        request_id=get_request_id() or "",
        metadata=metadata or {},
    )


def emit_commerce_event(
    *,
    site,
    event_type: str,
    aggregate_type: str = "",
    aggregate_id: str = "",
    payload: dict | None = None,
) -> CommerceEvent:
    event = CommerceEvent.objects.create(
        site=site,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id or ""),
        request_id=get_request_id() or "",
        payload=payload or {},
    )
    try:
        from analytics.services import track_commerce_event

        track_commerce_event(
            site=site,
            event_name=event_type,
            payload=payload or {},
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id or ""),
        )
    except Exception:
        logger.exception("Failed to forward commerce event to analytics.")

    try:
        from builder.services import trigger_webhooks

        trigger_webhooks(site, event_type, payload or {})
    except Exception:
        logger.exception("Failed to dispatch commerce webhook event.")
    return event


def create_checkout_session(
    cart: Cart,
    *,
    shipping_address: dict | None = None,
    billing_address: dict | None = None,
    shipping_rate_id: int | None = None,
    discount_code: str = "",
    email: str = "",
    customer: Customer | None = None,
) -> CheckoutSession:
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        cart = recalculate_cart(cart)
        if not cart.items.exists():
            raise ValueError("Cart is empty.")

        pricing = calculate_pricing(
            cart,
            shipping_address=shipping_address or {},
            shipping_rate_id=shipping_rate_id,
            discount_code=discount_code,
        )
        ttl_minutes = int(getattr(settings, "COMMERCE_CHECKOUT_TTL_MINUTES", 30) or 30)
        checkout = CheckoutSession.objects.create(
            site=cart.site,
            cart=cart,
            customer=customer or cart.customer,
            email=(email or (customer.email if customer else "")).strip().lower(),
            currency=cart.currency,
            shipping_address=shipping_address or {},
            billing_address=billing_address or {},
            discount_code=(discount_code or "").strip().upper(),
            shipping_rate_id=shipping_rate_id,
            subtotal=pricing["subtotal"],
            shipping_total=pricing["shipping_total"],
            tax_total=pricing["tax_total"],
            discount_total=pricing["discount_total"],
            total=pricing["total"],
            pricing_details=pricing["pricing_details"],
            expires_at=timezone.now() + timedelta(minutes=max(1, ttl_minutes)),
        )
        _reserve_inventory_for_checkout(checkout)
    emit_commerce_event(
        site=cart.site,
        event_type=CommerceEvent.EVENT_BEGIN_CHECKOUT,
        aggregate_type="checkout_session",
        aggregate_id=str(checkout.id),
        payload={"checkout_session_id": checkout.id, "cart_id": cart.id, "total": str(checkout.total)},
    )
    return checkout


def expire_checkout_session(checkout: CheckoutSession) -> CheckoutSession:
    with transaction.atomic():
        checkout = CheckoutSession.objects.select_for_update().get(pk=checkout.pk)
        if checkout.status != CheckoutSession.STATUS_OPEN:
            return checkout
        _release_checkout_reservations(checkout, mark_status=StockReservation.STATUS_EXPIRED)
        checkout.status = CheckoutSession.STATUS_EXPIRED
        checkout.save(update_fields=["status", "updated_at"])
    return checkout


def create_order_from_checkout(
    checkout: CheckoutSession,
    *,
    customer_name: str,
    customer_email: str,
    customer_phone: str = "",
    notes: str = "",
    actor=None,
    newsletter_consent: bool = False,
    source: str = Order.SOURCE_STOREFRONT,
) -> Order:
    with transaction.atomic():
        checkout = CheckoutSession.objects.select_for_update().select_related("site", "cart").get(pk=checkout.pk)
        if checkout.status != CheckoutSession.STATUS_OPEN:
            raise ValueError("Checkout session is not open.")
        if checkout.expires_at <= timezone.now():
            expire_checkout_session(checkout)
            raise ValueError("Checkout session has expired.")

        cart = Cart.objects.select_for_update().get(pk=checkout.cart_id)
        cart_items = list(cart.items.select_related("product_variant", "product_variant__product").all())
        if not cart_items:
            raise ValueError("Cart is empty.")

        customer, customer_created = _upsert_customer(
            site=checkout.site,
            customer_email=customer_email,
            customer_name=customer_name,
            customer_phone=customer_phone,
            newsletter_consent=newsletter_consent,
            user=actor,
        )

        order = Order.objects.create(
            site=checkout.site,
            customer=customer,
            checkout_session=checkout,
            order_number=build_order_number(checkout.site_id),
            status=Order.STATUS_PENDING,
            payment_status=Order.PAYMENT_PENDING,
            fulfillment_status=Order.FULFILLMENT_UNFULFILLED,
            source=source,
            currency=checkout.currency,
            customer_name=customer_name[:180],
            customer_email=customer_email.strip().lower(),
            customer_phone=customer_phone[:40],
            billing_address=checkout.billing_address or {},
            shipping_address=checkout.shipping_address or {},
            notes=(notes or "")[:4000],
            subtotal=checkout.subtotal,
            shipping_total=checkout.shipping_total,
            tax_total=checkout.tax_total,
            discount_total=checkout.discount_total,
            total=checkout.total,
            pricing_details=checkout.pricing_details or {},
        )

        for item in cart_items:
            variant = item.product_variant
            OrderItem.objects.create(
                order=order,
                product=variant.product,
                product_variant=variant,
                title=variant.product.title if variant.is_default else f"{variant.product.title} / {variant.title}",
                sku=variant.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
                attributes=variant.attributes or {},
            )

        _commit_checkout_reservations(checkout, order)

        if checkout.discount_code:
            discount = DiscountCode.objects.filter(site=checkout.site, code__iexact=checkout.discount_code).first()
            if discount:
                discount.use_count = F("use_count") + 1
                discount.save(update_fields=["use_count"])

        tax_rate_id = (checkout.pricing_details or {}).get("tax_rate_id")
        if tax_rate_id:
            TaxRecord.objects.create(
                site=checkout.site,
                order=order,
                provider="internal",
                jurisdiction=f"{(checkout.shipping_address or {}).get('country', '')}:{(checkout.shipping_address or {}).get('state', '')}".strip(
                    ":"
                ),
                rate=quantize_money(order.tax_total / max(order.subtotal + order.shipping_total, Decimal("1"))),
                taxable_amount=quantize_money(order.subtotal + order.shipping_total),
                tax_amount=order.tax_total,
                currency=order.currency,
                payload={"tax_rate_id": tax_rate_id},
            )

        cart.status = Cart.STATUS_CONVERTED
        cart.converted_at = timezone.now()
        cart.customer = customer
        cart.save(update_fields=["status", "converted_at", "customer", "updated_at"])

        checkout.status = CheckoutSession.STATUS_COMPLETED
        checkout.customer = customer
        checkout.completed_at = timezone.now()
        checkout.save(update_fields=["status", "customer", "completed_at", "updated_at"])

        customer.last_order_at = timezone.now()
        customer.save(update_fields=["last_order_at", "updated_at"])

        log_order_audit(
            order,
            action="order.created",
            actor=actor,
            message="Order created from checkout session.",
            metadata={"checkout_session_id": checkout.id},
        )

    emit_commerce_event(
        site=order.site,
        event_type=CommerceEvent.EVENT_PURCHASE,
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={"order_id": order.id, "order_number": order.order_number, "total": str(order.total)},
    )
    try:
        from notifications.services import trigger_webhooks

        trigger_webhooks(
            order.site,
            "order.created",
            {"order_id": order.id, "order_number": order.order_number, "total": str(order.total)},
        )
        if customer_created:
            trigger_webhooks(
                order.site,
                "customer.created",
                {"customer_id": customer.id, "email": customer.email},
            )
    except Exception:
        logger.exception("Failed to dispatch automation hooks for order/customer creation.")
    return order


def create_payment_intent(order: Order) -> Payment:
    intent = payment_gateway.create_intent(order, request_id=get_request_id() or "")
    payment, _ = Payment.objects.update_or_create(
        site=order.site,
        provider=intent.provider,
        provider_payment_id=intent.intent_id,
        defaults={
            "order": order,
            "idempotency_key": intent.idempotency_key,
            "amount": quantize_money(Decimal(intent.amount) / Decimal("100")),
            "currency": intent.currency.upper(),
            "status": Payment.STATUS_PENDING,
            "payload": {"client_secret": intent.client_secret},
        },
    )
    order.payment_provider = intent.provider
    order.payment_reference = intent.intent_id
    order.save(update_fields=["payment_provider", "payment_reference", "updated_at"])
    return payment


def mark_payment_result(
    order: Order,
    *,
    success: bool,
    provider_payment_id: str = "",
    provider: str = "stripe",
    payload: dict | None = None,
    error_message: str = "",
) -> Payment:
    payment = Payment.objects.filter(order=order, provider=provider).order_by("-created_at").first()
    if payment is None:
        payment = Payment.objects.create(
            site=order.site,
            order=order,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=order.total,
            currency=order.currency,
            status=Payment.STATUS_PENDING,
        )

    payment.provider_payment_id = provider_payment_id or payment.provider_payment_id
    payment.status = Payment.STATUS_SUCCEEDED if success else Payment.STATUS_FAILED
    payment.error_message = (error_message or "")[:2000]
    payment.payload = payload or {}
    payment.processed_at = timezone.now()
    payment.save(
        update_fields=["provider_payment_id", "status", "error_message", "payload", "processed_at", "updated_at"]
    )

    if success:
        order.payment_status = Order.PAYMENT_PAID
        order.status = Order.STATUS_PAID
        order.paid_at = timezone.now()
        order.save(update_fields=["payment_status", "status", "paid_at", "updated_at"])
        log_order_audit(
            order,
            action="payment.succeeded",
            message="Payment succeeded.",
            metadata={"payment_id": payment.id},
        )
    else:
        order.payment_status = Order.PAYMENT_FAILED
        order.save(update_fields=["payment_status", "updated_at"])
        log_order_audit(
            order,
            action="payment.failed",
            message="Payment failed.",
            metadata={"payment_id": payment.id, "error_message": error_message},
        )
    return payment


def refund_order(order: Order, *, amount: Decimal | None = None, reason: str = "", actor=None) -> Refund:
    amount = quantize_money(amount or order.total)
    result = payment_gateway.refund(order, amount=amount)
    if not result.get("success"):
        raise ValueError(result.get("error") or "Refund failed.")

    payment = order.payments.order_by("-created_at").first()
    refund = Refund.objects.create(
        site=order.site,
        order=order,
        payment=payment,
        provider_refund_id=result.get("refund_id", ""),
        amount=amount,
        currency=order.currency,
        reason=(reason or "")[:240],
        status=Refund.STATUS_SUCCEEDED,
        metadata={"provider_payload": result},
        processed_at=timezone.now(),
    )

    order.refunds_total = quantize_money(order.refunds_total + amount)
    is_full_refund = order.refunds_total >= order.total
    order.payment_status = Order.PAYMENT_REFUNDED if is_full_refund else Order.PAYMENT_PARTIALLY_REFUNDED
    if is_full_refund:
        order.status = Order.STATUS_CANCELLED
        order.cancelled_at = timezone.now()
        order.refunded_at = timezone.now()
    order.save(update_fields=["refunds_total", "payment_status", "status", "cancelled_at", "refunded_at", "updated_at"])

    if payment:
        payment.status = Payment.STATUS_REFUNDED if is_full_refund else Payment.STATUS_PARTIALLY_REFUNDED
        payment.save(update_fields=["status", "updated_at"])

    log_order_audit(
        order,
        action="refund.created",
        actor=actor,
        message="Refund issued.",
        metadata={"refund_id": refund.id, "amount": str(refund.amount)},
    )
    emit_commerce_event(
        site=order.site,
        event_type=CommerceEvent.EVENT_REFUND,
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={"order_id": order.id, "refund_id": refund.id, "amount": str(refund.amount)},
    )
    return refund


def capture_fraud_signal(
    *,
    site,
    order: Order | None = None,
    checkout_session: CheckoutSession | None = None,
    request=None,
    signal_type: str = "generic",
    score: Decimal | float | int = 0,
    metadata: dict | None = None,
) -> FraudSignal:
    ip_address = None
    user_agent = ""
    email = ""
    if request is not None:
        ip_address = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:500]
    if checkout_session:
        email = checkout_session.email
    elif order:
        email = order.customer_email

    return FraudSignal.objects.create(
        site=site,
        order=order,
        checkout_session=checkout_session,
        ip_address=ip_address or None,
        user_agent=user_agent,
        email=(email or "")[:254],
        signal_type=(signal_type or "generic")[:80],
        score=Decimal(str(score)),
        metadata=metadata or {},
    )


def send_receipt_email(order: Order) -> int:
    subject = f"Receipt for order {order.order_number}"
    body = (
        f"Thanks for your purchase.\n\n"
        f"Order: {order.order_number}\n"
        f"Total: {order.total} {order.currency}\n"
        f"Status: {order.status}\n"
    )
    return providers.email.send(
        subject=subject,
        body=body,
        to=[order.customer_email],
    )


def product_seo_payload(product: Product, *, canonical_domain: str = "", scheme: str = "https") -> dict[str, Any]:
    canonical_url = f"{scheme}://{canonical_domain}/shop/{product.slug}/" if canonical_domain else ""
    return build_seo_payload(
        title=product.title,
        description=product.excerpt or product.title,
        canonical_url=canonical_url,
        payload=product.seo if isinstance(product.seo, dict) else {},
        default_title_prefix=f"{product.site.name} | ",
    )


__all__ = [
    "build_order_number",
    "calculate_pricing",
    "capture_fraud_signal",
    "create_checkout_session",
    "create_order_from_checkout",
    "create_payment_intent",
    "emit_commerce_event",
    "ensure_variant_inventory",
    "expire_checkout_session",
    "get_or_create_cart",
    "log_order_audit",
    "mark_payment_result",
    "quantize_money",
    "recalculate_cart",
    "refund_order",
    "resolve_variant",
    "send_receipt_email",
    "sync_cart_item",
    "product_seo_payload",
]
