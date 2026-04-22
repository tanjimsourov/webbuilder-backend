"""Core domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from core.views import (
    AppInstallationViewSet,
    AppRegistrationViewSet,
    AcceptInvitationView,
    DataDeletionJobViewSet,
    DataExportJobViewSet,
    DashboardSummaryView,
    DeclineInvitationView,
    FeatureFlagAssignmentViewSet,
    FeatureFlagViewSet,
    MyWorkspacesView,
    PrivacyConsentView,
    SiteLocaleViewSet,
    SiteViewSet,
    WorkspaceSearchView,
    WorkspaceViewSet,
)

router = SimpleRouter()
router.register("sites", SiteViewSet, basename="site")
router.register("site-locales", SiteLocaleViewSet, basename="site-locale")
router.register("workspaces", WorkspaceViewSet, basename="workspace")
router.register("privacy/exports", DataExportJobViewSet, basename="privacy-export")
router.register("privacy/deletions", DataDeletionJobViewSet, basename="privacy-deletion")
router.register("apps/registry", AppRegistrationViewSet, basename="app-registry")
router.register("apps/installations", AppInstallationViewSet, basename="app-installation")
router.register("feature-flags", FeatureFlagViewSet, basename="feature-flag")
router.register("feature-flag-assignments", FeatureFlagAssignmentViewSet, basename="feature-flag-assignment")

urlpatterns = [
    path("dashboard/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("search/", WorkspaceSearchView.as_view(), name="workspace-search"),
    path("workspaces/my/", MyWorkspacesView.as_view(), name="my-workspaces"),
    path("privacy/consent/", PrivacyConsentView.as_view(), name="privacy-consent"),
    path("workspaces/accept-invitation/", AcceptInvitationView.as_view(), name="accept-invitation"),
    path("workspaces/decline-invitation/", DeclineInvitationView.as_view(), name="decline-invitation"),
    path("", include(router.urls)),
]
