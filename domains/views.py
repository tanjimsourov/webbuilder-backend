"""Domains domain view wrappers."""

from __future__ import annotations

from builder.views import (
    DomainContactViewSet as BuilderDomainContactViewSet,
    DomainViewSet as BuilderDomainViewSet,
)


class DomainContactViewSet(BuilderDomainContactViewSet):
    """Domain contact endpoints."""


class DomainViewSet(BuilderDomainViewSet):
    """Domain management endpoints."""


__all__ = [
    "DomainContactViewSet",
    "DomainViewSet",
]
