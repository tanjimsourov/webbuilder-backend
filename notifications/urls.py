"""Notifications domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from notifications.views import WebhookViewSet

router = SimpleRouter()
router.register("webhooks", WebhookViewSet, basename="webhook")

urlpatterns = [
    path("", include(router.urls)),
]

