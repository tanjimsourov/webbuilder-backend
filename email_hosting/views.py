"""Email hosting domain view wrappers."""

from __future__ import annotations

from builder.email_views import (
    EmailDomainCreateView as BuilderEmailDomainCreateView,
    EmailDomainViewSet as BuilderEmailDomainViewSet,
    EmailProvisioningTaskViewSet as BuilderEmailProvisioningTaskViewSet,
    MailAliasViewSet as BuilderMailAliasViewSet,
    MailboxCreateView as BuilderMailboxCreateView,
    MailboxViewSet as BuilderMailboxViewSet,
)


class EmailDomainViewSet(BuilderEmailDomainViewSet):
    """Email domain CRUD endpoints."""


class MailboxViewSet(BuilderMailboxViewSet):
    """Mailbox CRUD endpoints."""


class MailAliasViewSet(BuilderMailAliasViewSet):
    """Mail alias CRUD endpoints."""


class EmailProvisioningTaskViewSet(BuilderEmailProvisioningTaskViewSet):
    """Provisioning task read endpoints."""


class EmailDomainCreateView(BuilderEmailDomainCreateView):
    """Email domain creation endpoint."""


class MailboxCreateView(BuilderMailboxCreateView):
    """Mailbox creation endpoint."""


__all__ = [
    "EmailDomainCreateView",
    "EmailDomainViewSet",
    "EmailProvisioningTaskViewSet",
    "MailAliasViewSet",
    "MailboxCreateView",
    "MailboxViewSet",
]
