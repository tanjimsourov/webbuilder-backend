"""Domains domain view wrappers."""

from __future__ import annotations

from builder.views import (
    DomainContactViewSet as BuilderDomainContactViewSet,
    DomainViewSet as BuilderDomainViewSet,
)


DomainContactViewSet = BuilderDomainContactViewSet
DomainViewSet = BuilderDomainViewSet


__all__ = [
    "DomainContactViewSet",
    "DomainViewSet",
]
