"""Notifications domain serializers (transitional exports)."""

from builder.serializers import (  # noqa: F401
    EmailDomainCreateSerializer,
    EmailDomainSerializer,
    EmailProvisioningTaskSerializer,
    MailAliasSerializer,
    MailboxCreateSerializer,
    MailboxSerializer,
    WebhookSerializer,
)

__all__ = [
    "EmailDomainCreateSerializer",
    "EmailDomainSerializer",
    "EmailProvisioningTaskSerializer",
    "MailAliasSerializer",
    "MailboxCreateSerializer",
    "MailboxSerializer",
    "WebhookSerializer",
]
