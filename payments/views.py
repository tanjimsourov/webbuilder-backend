"""Payments API views."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from rest_framework import mixins, permissions, response, status, viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView

from payments.models import Invoice, Subscription, SubscriptionPlan
from payments.serializers import (
    CustomerSubscriptionSerializer,
    InvoiceSerializer,
    SubscriptionPlanSerializer,
)
from payments.services import create_checkout_session, get_publishable_key, handle_webhook

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None


class SubscriptionPlanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SubscriptionPlan.objects.filter(is_active=True).order_by("amount", "price")
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.AllowAny]


class CustomerSubscriptionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CustomerSubscriptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Subscription.objects.filter(customer=user).select_related("plan", "workspace")

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        subscription = self.get_object()
        payload = create_checkout_session(request, subscription.plan, customer_email=request.user.email)
        return response.Response(payload, status=status.HTTP_201_CREATED)


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Invoice.objects.filter(subscription__customer=self.request.user)
            .select_related("subscription", "transaction")
            .order_by("-issued_at")
        )


class CheckoutSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: HttpRequest):
        plan_id = request.data.get("plan_id")
        if not plan_id:
            return response.Response({"detail": "plan_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            plan = SubscriptionPlan.objects.get(pk=plan_id, is_active=True)
        except SubscriptionPlan.DoesNotExist:
            return response.Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = create_checkout_session(request, plan, customer_email=request.user.email)
        return response.Response(payload, status=status.HTTP_201_CREATED)


class StripeWebhookView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = []

    def get_throttles(self):
        from builder.throttles import WebhookThrottle

        return [WebhookThrottle()]

    def post(self, request: HttpRequest):
        payload = request.body
        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        webhook_secret = settings.STRIPE_WEBHOOK_SECRET
        if not stripe or not webhook_secret:
            return response.Response(
                {"detail": "Stripe webhook processing is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not signature:
            return response.Response({"detail": "Missing signature."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=webhook_secret)
        except stripe.error.SignatureVerificationError:
            return response.Response({"detail": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return response.Response({"detail": "Invalid payload."}, status=status.HTTP_400_BAD_REQUEST)

        event_id = str(event.get("id") or "").strip()
        if event_id:
            cache_key = f"payments:stripe:webhook:{event_id}"
            ttl_seconds = int(getattr(settings, "PAYMENT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS", 604800) or 604800)
            if not cache.add(cache_key, True, timeout=max(ttl_seconds, 1)):
                return response.Response({"received": True, "duplicate": True})

        handle_webhook(event)
        return response.Response({"received": True})


class PaymentConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return response.Response({"publishable_key": get_publishable_key()})


class PaymentSuccessView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return response.Response({"status": "success"})


class PaymentCancelView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return response.Response({"status": "cancelled"})


__all__ = [
    "CheckoutSessionView",
    "CustomerSubscriptionViewSet",
    "InvoiceViewSet",
    "PaymentCancelView",
    "PaymentConfigView",
    "PaymentSuccessView",
    "StripeWebhookView",
    "SubscriptionPlanViewSet",
]
