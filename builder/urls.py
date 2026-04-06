"""Builder-owned API routes.

This module intentionally keeps only platform/system endpoints that still
belong to the builder app. Domain APIs are mounted from their owning apps.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from builder.ai_views import AppsCatalogView, AISiteBlueprintApplyView, AISiteBlueprintView, AISuggestionView
from builder.platform_admin_views import (
    PlatformAdminOverviewView,
    PlatformAdminUserStatusView,
    PlatformAdminUsersView,
    PlatformAdminWorkspacesView,
    PlatformEmailCampaignViewSet,
    PlatformOfferViewSet,
    PlatformSubscriptionViewSet,
)
from builder.views import (
    AuthBootstrapView,
    AuthLoginView,
    AuthMagicLoginView,
    AuthLogoutView,
    AuthStatusView,
    HealthCheckView,
    MetricsView,
)

router = SimpleRouter()
router.register("platform-subscriptions", PlatformSubscriptionViewSet, basename="platform-subscription")
router.register("platform-offers", PlatformOfferViewSet, basename="platform-offer")
router.register("platform-email-campaigns", PlatformEmailCampaignViewSet, basename="platform-email-campaign")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("auth/status/", AuthStatusView.as_view(), name="auth-status"),
    path("auth/bootstrap/", AuthBootstrapView.as_view(), name="auth-bootstrap"),
    path("auth/login/", AuthLoginView.as_view(), name="auth-login"),
    path("auth/magic-login/", AuthMagicLoginView.as_view(), name="auth-magic-login"),
    path("auth/logout/", AuthLogoutView.as_view(), name="auth-logout"),
    path("apps/", AppsCatalogView.as_view(), name="platform-apps"),
    path("ai/suggestions/", AISuggestionView.as_view(), name="ai-suggestions"),
    path("ai/site-blueprint/", AISiteBlueprintView.as_view(), name="ai-site-blueprint"),
    path("ai/site-blueprint/apply/", AISiteBlueprintApplyView.as_view(), name="ai-site-blueprint-apply"),
    path("platform-admin/overview/", PlatformAdminOverviewView.as_view(), name="platform-admin-overview"),
    path("platform-admin/users/", PlatformAdminUsersView.as_view(), name="platform-admin-users"),
    path("platform-admin/workspaces/", PlatformAdminWorkspacesView.as_view(), name="platform-admin-workspaces"),
    path(
        "platform-admin/users/<int:user_id>/<str:action>/",
        PlatformAdminUserStatusView.as_view(),
        name="platform-admin-user-status",
    ),
    path("", include(router.urls)),
]

