"""Domains domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from domains.views import DomainContactViewSet, DomainViewSet

router = SimpleRouter()
router.register("domain-contacts", DomainContactViewSet, basename="domain-contact")
router.register("domains", DomainViewSet, basename="domain")

urlpatterns = [
    path("", include(router.urls)),
]

