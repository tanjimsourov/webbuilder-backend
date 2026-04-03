"""URL routing for the payments app."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from payments.views import (
    CheckoutSessionView,
    CustomerSubscriptionViewSet,
    InvoiceViewSet,
    PaymentCancelView,
    PaymentConfigView,
    PaymentSuccessView,
    StripeWebhookView,
    SubscriptionPlanViewSet,
)

app_name = "payments"

router = DefaultRouter()
router.register("plans", SubscriptionPlanViewSet, basename="plan")
router.register("subscriptions", CustomerSubscriptionViewSet, basename="subscription")
router.register("invoices", InvoiceViewSet, basename="invoice")

urlpatterns = [
    path("", include(router.urls)),
    path("config/", PaymentConfigView.as_view(), name="config"),
    path("checkout/session/", CheckoutSessionView.as_view(), name="checkout"),
    path("webhooks/stripe/", StripeWebhookView.as_view(), name="webhook"),
    path("success/", PaymentSuccessView.as_view(), name="success"),
    path("cancel/", PaymentCancelView.as_view(), name="cancel"),
]
