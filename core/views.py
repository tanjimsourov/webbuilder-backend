"""Core domain views.

These exports let callers import core-facing views from ``core.views`` while
the implementation is progressively split out of ``builder.views``.
"""

from builder.views import (  # noqa: F401
    DashboardSummaryView,
    SiteLocaleViewSet,
    SiteObjectPermission,
    SitePermissionMixin,
    SiteViewSet,
    WorkspaceSearchView,
)

__all__ = [
    "DashboardSummaryView",
    "SiteLocaleViewSet",
    "SiteObjectPermission",
    "SitePermissionMixin",
    "SiteViewSet",
    "WorkspaceSearchView",
]
