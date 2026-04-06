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


SEOAnalyticsViewSet = BuilderSEOAnalyticsViewSet
SEOAuditViewSet = BuilderSEOAuditViewSet
TrackedKeywordViewSet = BuilderTrackedKeywordViewSet
KeywordRankEntryViewSet = BuilderKeywordRankEntryViewSet
SEOSettingsViewSet = BuilderSEOSettingsViewSet
GSCConnectView = BuilderGSCConnectView
GSCCallbackView = BuilderGSCCallbackView
GSCSyncView = BuilderGSCSyncView
GSCDisconnectView = BuilderGSCDisconnectView
GSCStatusView = BuilderGSCStatusView
GSCPropertiesView = BuilderGSCPropertiesView
GSCCredentialUpdateView = BuilderGSCCredentialUpdateView
LibreCrawlStatusView = BuilderLibreCrawlStatusView
SerpBearStatusView = BuilderSerpBearStatusView
UmamiStatusView = BuilderUmamiStatusView
PayloadCMSStatusView = BuilderPayloadCMSStatusView
PayloadEcommerceStatusView = BuilderPayloadEcommerceStatusView


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
