"""Notifications domain views (transitional exports)."""

from builder.email_views import (  # noqa: F401
    EmailDomainCreateView,
    EmailDomainViewSet,
    EmailProvisioningTaskViewSet,
    MailAliasViewSet,
    MailboxCreateView,
    MailboxViewSet,
)
from builder.views import WebhookViewSet  # noqa: F401

__all__ = [
    "EmailDomainCreateView",
    "EmailDomainViewSet",
    "EmailProvisioningTaskViewSet",
    "MailAliasViewSet",
    "MailboxCreateView",
    "MailboxViewSet",
    "WebhookViewSet",
]
