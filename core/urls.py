"""Core domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from core.views import (
    AcceptInvitationView,
    DashboardSummaryView,
    MyWorkspacesView,
    SiteLocaleViewSet,
    SiteViewSet,
    WorkspaceSearchView,
    WorkspaceViewSet,
)

router = SimpleRouter()
router.register("sites", SiteViewSet, basename="site")
router.register("site-locales", SiteLocaleViewSet, basename="site-locale")
router.register("workspaces", WorkspaceViewSet, basename="workspace")

urlpatterns = [
    path("dashboard/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("search/", WorkspaceSearchView.as_view(), name="workspace-search"),
    path("workspaces/my/", MyWorkspacesView.as_view(), name="my-workspaces"),
    path("workspaces/accept-invitation/", AcceptInvitationView.as_view(), name="accept-invitation"),
    path("", include(router.urls)),
]
