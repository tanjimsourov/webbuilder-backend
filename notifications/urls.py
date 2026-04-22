"""Notifications domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from notifications.views import NotificationViewSet, WebhookEndpointDeliveryViewSet, WebhookEndpointViewSet, WebhookViewSet

router = SimpleRouter()
router.register("webhooks", WebhookViewSet, basename="webhook")
router.register("integration-webhooks", WebhookEndpointViewSet, basename="integration-webhook")
router.register("integration-webhook-deliveries", WebhookEndpointDeliveryViewSet, basename="integration-webhook-delivery")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path("", include(router.urls)),
]

