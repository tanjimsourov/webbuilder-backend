"""Builder-owned API routes.

This module intentionally keeps only platform/system endpoints that still
belong to the builder app. Domain APIs are mounted from their owning apps.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from builder.ai_views import AppsCatalogView, AISiteBlueprintApplyView, AISiteBlueprintView, AISuggestionView
from builder.platform_admin_views import (
    PlatformAdminUserRoleAssignmentView,
    PlatformAdminSiteMembershipView,
    PlatformAdminUserSecurityTimelineView,
    PlatformAdminWorkspaceMembershipView,
    PlatformImpersonationStartView,
    PlatformImpersonationStopView,
    PlatformAdminOverviewView,
    PlatformAdminUserStatusView,
    PlatformAdminUsersView,
    PlatformAdminWorkspacesView,
    PlatformEmailCampaignViewSet,
    PlatformOfferViewSet,
    PlatformSubscriptionViewSet,
)
from builder.views import (
    AuthActivityTimelineView,
    AuthAPIKeyListCreateView,
    AuthAPIKeyRevokeView,
    AuthEmailVerificationConfirmView,
    AuthEmailVerificationRequestView,
    AuthBootstrapView,
    AuthChangePasswordView,
    AuthLoginView,
    AuthMFAChallengeVerifyView,
    AuthMFARecoveryCodesRegenerateView,
    AuthMFATOTPSetupView,
    AuthMFATOTPVerifyView,
    AuthMagicLoginView,
    AuthLogoutView,
    AuthPasswordResetConfirmView,
    AuthPasswordResetRequestView,
    AuthRegisterView,
    AuthSessionListView,
    AuthSessionRevokeOthersView,
    AuthSessionRevokeView,
    AuthSocialLoginView,
    AuthStatusView,
    AuthTokenIssueView,
    AuthTokenRefreshView,
    AuthTokenRevokeView,
    HealthCheckView,
    LivenessCheckView,
    MetricsView,
    ReadinessCheckView,
    VersionView,
)

router = SimpleRouter()
router.register("platform-subscriptions", PlatformSubscriptionViewSet, basename="platform-subscription")
router.register("platform-offers", PlatformOfferViewSet, basename="platform-offer")
router.register("platform-email-campaigns", PlatformEmailCampaignViewSet, basename="platform-email-campaign")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("live/", LivenessCheckView.as_view(), name="liveness-check"),
    path("ready/", ReadinessCheckView.as_view(), name="readiness-check"),
    path("version/", VersionView.as_view(), name="version"),
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("auth/status/", AuthStatusView.as_view(), name="auth-status"),
    path("auth/register/", AuthRegisterView.as_view(), name="auth-register"),
    path("auth/bootstrap/", AuthBootstrapView.as_view(), name="auth-bootstrap"),
    path("auth/login/", AuthLoginView.as_view(), name="auth-login"),
    path("auth/login/mfa/", AuthMFAChallengeVerifyView.as_view(), name="auth-mfa-challenge-verify"),
    path("auth/magic-login/", AuthMagicLoginView.as_view(), name="auth-magic-login"),
    path("auth/logout/", AuthLogoutView.as_view(), name="auth-logout"),
    path("auth/change-password/", AuthChangePasswordView.as_view(), name="auth-change-password"),
    path("auth/tokens/issue/", AuthTokenIssueView.as_view(), name="auth-token-issue"),
    path("auth/tokens/refresh/", AuthTokenRefreshView.as_view(), name="auth-token-refresh"),
    path("auth/tokens/revoke/", AuthTokenRevokeView.as_view(), name="auth-token-revoke"),
    path(
        "auth/email-verification/request/",
        AuthEmailVerificationRequestView.as_view(),
        name="auth-email-verification-request",
    ),
    path(
        "auth/email-verification/resend/",
        AuthEmailVerificationRequestView.as_view(),
        name="auth-email-verification-resend",
    ),
    path(
        "auth/email-verification/confirm/",
        AuthEmailVerificationConfirmView.as_view(),
        name="auth-email-verification-confirm",
    ),
    path("auth/password-reset/request/", AuthPasswordResetRequestView.as_view(), name="auth-password-reset-request"),
    path("auth/password-reset/confirm/", AuthPasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("auth/social/login/", AuthSocialLoginView.as_view(), name="auth-social-login"),
    path("auth/mfa/totp/setup/", AuthMFATOTPSetupView.as_view(), name="auth-mfa-totp-setup"),
    path("auth/mfa/totp/verify/", AuthMFATOTPVerifyView.as_view(), name="auth-mfa-totp-verify"),
    path(
        "auth/mfa/recovery-codes/regenerate/",
        AuthMFARecoveryCodesRegenerateView.as_view(),
        name="auth-mfa-recovery-regenerate",
    ),
    path("auth/sessions/", AuthSessionListView.as_view(), name="auth-sessions"),
    path("auth/sessions/revoke/", AuthSessionRevokeView.as_view(), name="auth-sessions-revoke"),
    path("auth/sessions/revoke-others/", AuthSessionRevokeOthersView.as_view(), name="auth-sessions-revoke-others"),
    path("auth/activity/", AuthActivityTimelineView.as_view(), name="auth-activity"),
    path("auth/api-keys/", AuthAPIKeyListCreateView.as_view(), name="auth-api-keys"),
    path("auth/api-keys/<int:key_id>/revoke/", AuthAPIKeyRevokeView.as_view(), name="auth-api-key-revoke"),
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
    path(
        "platform-admin/users/<int:user_id>/roles/",
        PlatformAdminUserRoleAssignmentView.as_view(),
        name="platform-admin-user-roles",
    ),
    path(
        "platform-admin/users/<int:user_id>/security-events/",
        PlatformAdminUserSecurityTimelineView.as_view(),
        name="platform-admin-user-security-events",
    ),
    path(
        "platform-admin/workspaces/<int:workspace_id>/memberships/",
        PlatformAdminWorkspaceMembershipView.as_view(),
        name="platform-admin-workspace-memberships",
    ),
    path(
        "platform-admin/workspaces/<int:workspace_id>/memberships/<int:membership_id>/",
        PlatformAdminWorkspaceMembershipView.as_view(),
        name="platform-admin-workspace-membership-detail",
    ),
    path(
        "platform-admin/sites/<int:site_id>/memberships/",
        PlatformAdminSiteMembershipView.as_view(),
        name="platform-admin-site-memberships",
    ),
    path(
        "platform-admin/sites/<int:site_id>/memberships/<int:membership_id>/",
        PlatformAdminSiteMembershipView.as_view(),
        name="platform-admin-site-membership-detail",
    ),
    path(
        "platform-admin/impersonation/start/",
        PlatformImpersonationStartView.as_view(),
        name="platform-admin-impersonation-start",
    ),
    path(
        "platform-admin/impersonation/stop/",
        PlatformImpersonationStopView.as_view(),
        name="platform-admin-impersonation-stop",
    ),
    path("", include(router.urls)),
]

