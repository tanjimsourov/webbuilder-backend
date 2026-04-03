"""Analytics domain view wrappers."""

from __future__ import annotations

from builder.views import (
    GSCCallbackView as BuilderGSCCallbackView,
    GSCConnectView as BuilderGSCConnectView,
    GSCCredentialUpdateView as BuilderGSCCredentialUpdateView,
    GSCDisconnectView as BuilderGSCDisconnectView,
    GSCPropertiesView as BuilderGSCPropertiesView,
    GSCStatusView as BuilderGSCStatusView,
    GSCSyncView as BuilderGSCSyncView,
    KeywordRankEntryViewSet as BuilderKeywordRankEntryViewSet,
    LibreCrawlStatusView as BuilderLibreCrawlStatusView,
    PayloadCMSStatusView as BuilderPayloadCMSStatusView,
    PayloadEcommerceStatusView as BuilderPayloadEcommerceStatusView,
    SEOAnalyticsViewSet as BuilderSEOAnalyticsViewSet,
    SEOAuditViewSet as BuilderSEOAuditViewSet,
    SEOSettingsViewSet as BuilderSEOSettingsViewSet,
    SerpBearStatusView as BuilderSerpBearStatusView,
    TrackedKeywordViewSet as BuilderTrackedKeywordViewSet,
    UmamiStatusView as BuilderUmamiStatusView,
)


class SEOAnalyticsViewSet(BuilderSEOAnalyticsViewSet):
    """SEO analytics endpoints."""


class SEOAuditViewSet(BuilderSEOAuditViewSet):
    """SEO audit endpoints."""


class TrackedKeywordViewSet(BuilderTrackedKeywordViewSet):
    """Keyword tracking endpoints."""


class KeywordRankEntryViewSet(BuilderKeywordRankEntryViewSet):
    """Keyword rank history endpoints."""


class SEOSettingsViewSet(BuilderSEOSettingsViewSet):
    """SEO settings endpoints."""


class GSCConnectView(BuilderGSCConnectView):
    """GSC OAuth connect endpoint."""


class GSCCallbackView(BuilderGSCCallbackView):
    """GSC OAuth callback endpoint."""


class GSCSyncView(BuilderGSCSyncView):
    """GSC sync endpoint."""


class GSCDisconnectView(BuilderGSCDisconnectView):
    """GSC disconnect endpoint."""


class GSCStatusView(BuilderGSCStatusView):
    """GSC status endpoint."""


class GSCPropertiesView(BuilderGSCPropertiesView):
    """GSC properties endpoint."""


class GSCCredentialUpdateView(BuilderGSCCredentialUpdateView):
    """GSC credential update endpoint."""


class LibreCrawlStatusView(BuilderLibreCrawlStatusView):
    """LibreCrawl integration status endpoint."""


class SerpBearStatusView(BuilderSerpBearStatusView):
    """SerpBear integration status endpoint."""


class UmamiStatusView(BuilderUmamiStatusView):
    """Umami integration status endpoint."""


class PayloadCMSStatusView(BuilderPayloadCMSStatusView):
    """Payload CMS integration status endpoint."""


class PayloadEcommerceStatusView(BuilderPayloadEcommerceStatusView):
    """Payload e-commerce integration status endpoint."""


__all__ = [
    "GSCCallbackView",
    "GSCConnectView",
    "GSCCredentialUpdateView",
    "GSCDisconnectView",
    "GSCPropertiesView",
    "GSCStatusView",
    "GSCSyncView",
    "KeywordRankEntryViewSet",
    "LibreCrawlStatusView",
    "PayloadCMSStatusView",
    "PayloadEcommerceStatusView",
    "SEOAnalyticsViewSet",
    "SEOAuditViewSet",
    "SEOSettingsViewSet",
    "SerpBearStatusView",
    "TrackedKeywordViewSet",
    "UmamiStatusView",
]
