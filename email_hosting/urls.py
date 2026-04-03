"""URL routes for the email hosting domain."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from email_hosting.views import (
    EmailDomainCreateView,
    EmailDomainViewSet,
    EmailProvisioningTaskViewSet,
    MailAliasViewSet,
    MailboxCreateView,
    MailboxViewSet,
)

app_name = "email_hosting"

router = DefaultRouter()
router.register("domains", EmailDomainViewSet, basename="domain")
router.register("mailboxes", MailboxViewSet, basename="mailbox")
router.register("aliases", MailAliasViewSet, basename="alias")
router.register("tasks", EmailProvisioningTaskViewSet, basename="task")

urlpatterns = [
    path("", include(router.urls)),
    path("domains/create/", EmailDomainCreateView.as_view(), name="domain-create"),
    path("mailboxes/create/", MailboxCreateView.as_view(), name="mailbox-create"),
]
