"""Notifications domain view wrappers.

Email hosting views are re-exported here for backwards compatibility with
existing URL imports.
"""

from __future__ import annotations

from builder.views import WebhookViewSet as BuilderWebhookViewSet
from email_hosting.views import (
    EmailDomainCreateView,
    EmailDomainViewSet,
    EmailProvisioningTaskViewSet,
    MailAliasViewSet,
    MailboxCreateView,
    MailboxViewSet,
)


class WebhookViewSet(BuilderWebhookViewSet):
    """Webhook configuration endpoints."""


__all__ = [
    "EmailDomainCreateView",
    "EmailDomainViewSet",
    "EmailProvisioningTaskViewSet",
    "MailAliasViewSet",
    "MailboxCreateView",
    "MailboxViewSet",
    "WebhookViewSet",
]
