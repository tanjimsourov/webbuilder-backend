"""Analytics domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from analytics.views import (
    GSCCallbackView,
    GSCConnectView,
    GSCCredentialUpdateView,
    GSCDisconnectView,
    GSCPropertiesView,
    GSCStatusView,
    GSCSyncView,
    KeywordRankEntryViewSet,
    LibreCrawlStatusView,
    PayloadCMSStatusView,
    PayloadEcommerceStatusView,
    SEOAnalyticsViewSet,
    SEOAuditViewSet,
    SEOSettingsViewSet,
    SerpBearStatusView,
    TrackedKeywordViewSet,
    UmamiStatusView,
)

router = SimpleRouter()
router.register("seo-analytics", SEOAnalyticsViewSet, basename="seo-analytics")
router.register("seo-audits", SEOAuditViewSet, basename="seo-audit")
router.register("seo-settings", SEOSettingsViewSet, basename="seo-settings")
router.register("tracked-keywords", TrackedKeywordViewSet, basename="tracked-keyword")
router.register("keyword-ranks", KeywordRankEntryViewSet, basename="keyword-rank")

urlpatterns = [
    path("seo/librecrawl/status/", LibreCrawlStatusView.as_view(), name="librecrawl-status"),
    path("seo/serpbear/status/", SerpBearStatusView.as_view(), name="serpbear-status"),
    path("analytics/umami/status/", UmamiStatusView.as_view(), name="umami-status"),
    path("cms/payload/status/", PayloadCMSStatusView.as_view(), name="payload-cms-status"),
    path("commerce/payload/status/", PayloadEcommerceStatusView.as_view(), name="payload-ecommerce-status"),
    path("seo/gsc/connect/", GSCConnectView.as_view(), name="gsc-connect"),
    path("seo/gsc/callback/", GSCCallbackView.as_view(), name="gsc-callback"),
    path("seo/gsc/sync/", GSCSyncView.as_view(), name="gsc-sync"),
    path("seo/gsc/disconnect/", GSCDisconnectView.as_view(), name="gsc-disconnect"),
    path("seo/gsc/status/", GSCStatusView.as_view(), name="gsc-status"),
    path("seo/gsc/properties/", GSCPropertiesView.as_view(), name="gsc-properties"),
    path("seo/gsc/credential/", GSCCredentialUpdateView.as_view(), name="gsc-credential"),
    path("", include(router.urls)),
]

