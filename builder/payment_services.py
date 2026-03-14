"""
Payment service abstraction layer.

Provides a unified interface for payment processing with Stripe as the primary provider.
Designed to be extensible for future payment gateway support (PayPal, etc.).

Environment Variables Required:
- STRIPE_SECRET_KEY: Stripe secret API key
- STRIPE_WEBHOOK_SECRET: Stripe webhook signing secret
- STRIPE_PUBLISHABLE_KEY: Stripe publishable key (for frontend)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class PaymentProvider(str, Enum):
    STRIPE = "stripe"
    PAYPAL = "paypal"  # Future support
    MANUAL = "manual"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class PaymentIntent:
    """Represents a payment intent from any provider."""
    provider: PaymentProvider
    intent_id: str
    client_secret: str
    amount: int  # In smallest currency unit (cents)
    currency: str
    status: PaymentStatus
    metadata: dict
    created_at: float


@dataclass
class PaymentResult:
    """Result of a payment operation."""
    success: bool
    provider: PaymentProvider
    payment_id: str
    status: PaymentStatus
    amount: int
    currency: str
    error_message: str = ""
    error_code: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class RefundResult:
    """Result of a refund operation."""
    success: bool
    refund_id: str
    amount: int
    status: str
    error_message: str = ""


class PaymentGateway(ABC):
    """Abstract base class for payment gateways."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the gateway is properly configured."""
        pass

    @abstractmethod
    def create_payment_intent(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        metadata: dict = None,
    ) -> PaymentIntent:
        """Create a payment intent for the given amount."""
        pass

    @abstractmethod
    def confirm_payment(self, payment_intent_id: str) -> PaymentResult:
        """Confirm/capture a payment intent."""
        pass

    @abstractmethod
    def cancel_payment(self, payment_intent_id: str) -> PaymentResult:
        """Cancel a payment intent."""
        pass

    @abstractmethod
    def refund_payment(
        self, payment_intent_id: str, amount: Optional[int] = None
    ) -> RefundResult:
        """Refund a payment (full or partial)."""
        pass

    @abstractmethod
    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> bool:
        """Verify webhook signature from the provider."""
        pass

    @abstractmethod
    def parse_webhook_event(self, payload: bytes) -> dict:
        """Parse webhook payload into a standardized event dict."""
        pass


class StripeGateway(PaymentGateway):
    """Stripe payment gateway implementation."""

    def __init__(self):
        self._secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
        self._webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._publishable_key = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
        self._stripe = None

    def _get_stripe(self):
        """Lazy-load stripe module."""
        if self._stripe is None:
            try:
                import stripe
                stripe.api_key = self._secret_key
                self._stripe = stripe
            except ImportError:
                logger.warning("Stripe package not installed. Run: pip install stripe")
                return None
        return self._stripe

    def is_configured(self) -> bool:
        """Check if Stripe is properly configured."""
        return bool(self._secret_key and self._secret_key.startswith("sk_"))

    def get_publishable_key(self) -> str:
        """Get the publishable key for frontend use."""
        return self._publishable_key

    def create_payment_intent(
        self,
        amount: int,
        currency: str,
        order_id: str,
        customer_email: str,
        metadata: dict = None,
    ) -> PaymentIntent:
        """Create a Stripe PaymentIntent."""
        stripe = self._get_stripe()
        if not stripe:
            raise PaymentConfigurationError("Stripe is not installed")

        if not self.is_configured():
            raise PaymentConfigurationError("Stripe is not configured. Set STRIPE_SECRET_KEY.")

        meta = {
            "order_id": order_id,
            "customer_email": customer_email,
            **(metadata or {}),
        }

        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency.lower(),
                metadata=meta,
                receipt_email=customer_email,
                automatic_payment_methods={"enabled": True},
            )

            return PaymentIntent(
                provider=PaymentProvider.STRIPE,
                intent_id=intent.id,
                client_secret=intent.client_secret,
                amount=intent.amount,
                currency=intent.currency,
                status=self._map_stripe_status(intent.status),
                metadata=dict(intent.metadata),
                created_at=intent.created,
            )
        except stripe.error.StripeError as e:
            logger.error(f"Stripe PaymentIntent creation failed: {e}")
            raise PaymentError(str(e), code=getattr(e, "code", "unknown"))

    def confirm_payment(self, payment_intent_id: str) -> PaymentResult:
        """Retrieve and confirm payment status."""
        stripe = self._get_stripe()
        if not stripe or not self.is_configured():
            raise PaymentConfigurationError("Stripe is not configured")

        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            return PaymentResult(
                success=intent.status == "succeeded",
                provider=PaymentProvider.STRIPE,
                payment_id=intent.id,
                status=self._map_stripe_status(intent.status),
                amount=intent.amount,
                currency=intent.currency,
                metadata=dict(intent.metadata),
            )
        except stripe.error.StripeError as e:
            return PaymentResult(
                success=False,
                provider=PaymentProvider.STRIPE,
                payment_id=payment_intent_id,
                status=PaymentStatus.FAILED,
                amount=0,
                currency="",
                error_message=str(e),
                error_code=getattr(e, "code", "unknown"),
            )

    def cancel_payment(self, payment_intent_id: str) -> PaymentResult:
        """Cancel a payment intent."""
        stripe = self._get_stripe()
        if not stripe or not self.is_configured():
            raise PaymentConfigurationError("Stripe is not configured")

        try:
            intent = stripe.PaymentIntent.cancel(payment_intent_id)
            return PaymentResult(
                success=True,
                provider=PaymentProvider.STRIPE,
                payment_id=intent.id,
                status=PaymentStatus.CANCELLED,
                amount=intent.amount,
                currency=intent.currency,
            )
        except stripe.error.StripeError as e:
            return PaymentResult(
                success=False,
                provider=PaymentProvider.STRIPE,
                payment_id=payment_intent_id,
                status=PaymentStatus.FAILED,
                amount=0,
                currency="",
                error_message=str(e),
            )

    def refund_payment(
        self, payment_intent_id: str, amount: Optional[int] = None
    ) -> RefundResult:
        """Create a refund for a payment."""
        stripe = self._get_stripe()
        if not stripe or not self.is_configured():
            raise PaymentConfigurationError("Stripe is not configured")

        try:
            refund_params = {"payment_intent": payment_intent_id}
            if amount is not None:
                refund_params["amount"] = amount

            refund = stripe.Refund.create(**refund_params)
            return RefundResult(
                success=True,
                refund_id=refund.id,
                amount=refund.amount,
                status=refund.status,
            )
        except stripe.error.StripeError as e:
            return RefundResult(
                success=False,
                refund_id="",
                amount=0,
                status="failed",
                error_message=str(e),
            )

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Stripe webhook signature."""
        stripe = self._get_stripe()
        if not stripe or not self._webhook_secret:
            return False

        try:
            stripe.Webhook.construct_event(
                payload, signature, self._webhook_secret
            )
            return True
        except (ValueError, stripe.error.SignatureVerificationError):
            return False

    def parse_webhook_event(self, payload: bytes) -> dict:
        """Parse Stripe webhook event."""
        stripe = self._get_stripe()
        if not stripe or not self._webhook_secret:
            raise PaymentConfigurationError("Stripe webhook secret not configured")

        try:
            # Get signature from the payload context (passed separately in view)
            event = json.loads(payload)
            return {
                "type": event.get("type", ""),
                "id": event.get("id", ""),
                "data": event.get("data", {}).get("object", {}),
                "created": event.get("created", 0),
                "raw": event,
            }
        except json.JSONDecodeError as e:
            raise PaymentError(f"Invalid webhook payload: {e}")

    def _map_stripe_status(self, stripe_status: str) -> PaymentStatus:
        """Map Stripe status to our PaymentStatus enum."""
        mapping = {
            "requires_payment_method": PaymentStatus.PENDING,
            "requires_confirmation": PaymentStatus.PENDING,
            "requires_action": PaymentStatus.PROCESSING,
            "processing": PaymentStatus.PROCESSING,
            "requires_capture": PaymentStatus.PROCESSING,
            "succeeded": PaymentStatus.SUCCEEDED,
            "canceled": PaymentStatus.CANCELLED,
        }
        return mapping.get(stripe_status, PaymentStatus.PENDING)


class PaymentError(Exception):
    """Base payment error."""

    def __init__(self, message: str, code: str = "payment_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class PaymentConfigurationError(PaymentError):
    """Payment gateway not configured."""

    def __init__(self, message: str):
        super().__init__(message, code="configuration_error")


class PaymentService:
    """
    High-level payment service that orchestrates payment operations.
    Handles order status transitions and payment persistence.
    """

    def __init__(self):
        self._gateways: dict[PaymentProvider, PaymentGateway] = {
            PaymentProvider.STRIPE: StripeGateway(),
        }
        self._default_provider = PaymentProvider.STRIPE

    def get_gateway(self, provider: PaymentProvider = None) -> PaymentGateway:
        """Get a payment gateway by provider."""
        provider = provider or self._default_provider
        gateway = self._gateways.get(provider)
        if not gateway:
            raise PaymentError(f"Payment provider {provider} not supported")
        return gateway

    def is_payment_configured(self, provider: PaymentProvider = None) -> bool:
        """Check if payment processing is configured."""
        try:
            gateway = self.get_gateway(provider)
            return gateway.is_configured()
        except PaymentError:
            return False

    def get_configuration_status(self) -> dict:
        """Get configuration status for all providers."""
        return {
            provider.value: self._gateways[provider].is_configured()
            for provider in self._gateways
        }

    def create_checkout_session(
        self,
        order,
        provider: PaymentProvider = None,
    ) -> PaymentIntent:
        """
        Create a payment intent for an order.
        Returns the client secret for frontend payment confirmation.
        """
        gateway = self.get_gateway(provider or self._default_provider)

        # Convert order total to cents
        amount_cents = int(order.total * 100)

        intent = gateway.create_payment_intent(
            amount=amount_cents,
            currency=order.currency,
            order_id=str(order.id),
            customer_email=order.customer_email,
            metadata={
                "order_number": order.order_number,
                "site_id": str(order.site_id),
            },
        )

        # Update order with payment reference
        order.payment_provider = intent.provider.value
        order.payment_reference = intent.intent_id
        order.save(update_fields=["payment_provider", "payment_reference", "updated_at"])

        return intent

    def process_webhook_event(self, provider: PaymentProvider, payload: bytes, signature: str) -> dict:
        """
        Process a webhook event from a payment provider.
        Returns the processed event data.
        """
        gateway = self.get_gateway(provider)

        # Verify signature
        if not gateway.verify_webhook_signature(payload, signature):
            raise PaymentError("Invalid webhook signature", code="invalid_signature")

        # Parse event
        event = gateway.parse_webhook_event(payload)

        # Handle specific event types
        event_type = event.get("type", "")
        event_data = event.get("data", {})

        if event_type == "payment_intent.succeeded":
            self._handle_payment_succeeded(event_data)
        elif event_type == "payment_intent.payment_failed":
            self._handle_payment_failed(event_data)
        elif event_type == "charge.refunded":
            self._handle_refund(event_data)

        return event

    def _handle_payment_succeeded(self, data: dict) -> None:
        """Handle successful payment event."""
        from .models import Order

        payment_intent_id = data.get("id", "")
        if not payment_intent_id:
            return

        try:
            order = Order.objects.get(payment_reference=payment_intent_id)
            order.payment_status = Order.PAYMENT_PAID
            order.status = Order.STATUS_PAID
            order.save(update_fields=["payment_status", "status", "updated_at"])

            # Trigger webhook
            from .services import trigger_webhooks
            trigger_webhooks(
                order.site,
                "order.paid",
                {
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "total": str(order.total),
                    "customer_email": order.customer_email,
                },
            )

            logger.info(f"Order {order.order_number} marked as paid via webhook")
        except Order.DoesNotExist:
            logger.warning(f"Order not found for payment intent: {payment_intent_id}")

    def _handle_payment_failed(self, data: dict) -> None:
        """Handle failed payment event."""
        from .models import Order

        payment_intent_id = data.get("id", "")
        if not payment_intent_id:
            return

        try:
            order = Order.objects.get(payment_reference=payment_intent_id)
            order.payment_status = Order.PAYMENT_FAILED
            order.save(update_fields=["payment_status", "updated_at"])
            logger.info(f"Order {order.order_number} payment failed via webhook")
        except Order.DoesNotExist:
            logger.warning(f"Order not found for payment intent: {payment_intent_id}")

    def _handle_refund(self, data: dict) -> None:
        """Handle refund event."""
        from .models import Order

        payment_intent_id = data.get("payment_intent", "")
        if not payment_intent_id:
            return

        try:
            order = Order.objects.get(payment_reference=payment_intent_id)
            # Check if fully refunded
            amount_refunded = data.get("amount_refunded", 0)
            amount_captured = data.get("amount", 0)

            if amount_refunded >= amount_captured:
                order.payment_status = Order.PAYMENT_REFUNDED
                order.status = Order.STATUS_CANCELLED
                order.save(update_fields=["payment_status", "status", "updated_at"])
                logger.info(f"Order {order.order_number} fully refunded via webhook")
        except Order.DoesNotExist:
            logger.warning(f"Order not found for refund: {payment_intent_id}")

    def refund_order(self, order, amount: Optional[Decimal] = None) -> RefundResult:
        """Refund an order (full or partial)."""
        if not order.payment_reference:
            raise PaymentError("Order has no payment reference")

        provider = PaymentProvider(order.payment_provider) if order.payment_provider else self._default_provider
        gateway = self.get_gateway(provider)

        amount_cents = int(amount * 100) if amount else None
        result = gateway.refund_payment(order.payment_reference, amount_cents)

        if result.success:
            if amount is None or amount >= order.total:
                order.payment_status = order.PAYMENT_REFUNDED
                order.status = order.STATUS_CANCELLED
            order.save(update_fields=["payment_status", "status", "updated_at"])

        return result


# Singleton instance
payment_service = PaymentService()


def get_payment_service() -> PaymentService:
    """Get the payment service singleton."""
    return payment_service


def get_stripe_publishable_key() -> str:
    """Get Stripe publishable key for frontend."""
    gateway = payment_service.get_gateway(PaymentProvider.STRIPE)
    if isinstance(gateway, StripeGateway):
        return gateway.get_publishable_key()
    return ""
