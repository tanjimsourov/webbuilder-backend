"""Analytics domain views."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from analytics.models import AnalyticsEvent, AnalyticsSession, CommerceAnalyticsEvent
from analytics.serializers import (
    AnalyticsEventSerializer,
    AnalyticsIngestSerializer,
    AnalyticsSessionSerializer,
    AnalyticsSummaryQuerySerializer,
    CommerceAnalyticsEventSerializer,
    SearchDocumentSerializer,
)
from analytics.services import analytics_funnel, analytics_summary, ingest_analytics_event
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
    SitePermissionMixin,
    TrackedKeywordViewSet as BuilderTrackedKeywordViewSet,
    UmamiStatusView as BuilderUmamiStatusView,
)
from core.models import Site
from shared.policies.access import SitePermission, has_site_permission


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


class CommerceAnalyticsEventViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CommerceAnalyticsEventSerializer

    def get_queryset(self):
        queryset = CommerceAnalyticsEvent.objects.select_related("site").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        event_name = self.request.query_params.get("event_name")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if event_name:
            queryset = queryset.filter(event_name=event_name)
        return self.filter_by_site_permission(queryset)


class AnalyticsSessionViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalyticsSessionSerializer

    def get_queryset(self):
        queryset = AnalyticsSession.objects.select_related("site").order_by("-last_seen_at")
        site_id = self.request.query_params.get("site")
        include_bots = (self.request.query_params.get("include_bots") or "").lower() in {"1", "true", "yes"}
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if not include_bots:
            queryset = queryset.filter(is_bot=False)
        return self.filter_by_site_permission(queryset)


class AnalyticsEventViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalyticsEventSerializer

    def get_queryset(self):
        queryset = AnalyticsEvent.objects.select_related("site", "session").order_by("-occurred_at")
        site_id = self.request.query_params.get("site")
        session_id = self.request.query_params.get("session")
        event_type = self.request.query_params.get("event_type")
        include_bots = (self.request.query_params.get("include_bots") or "").lower() in {"1", "true", "yes"}
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if session_id:
            queryset = queryset.filter(session_id=session_id)
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        if not include_bots:
            queryset = queryset.filter(is_bot=False)
        return self.filter_by_site_permission(queryset)


class SearchDocumentViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = SearchDocumentSerializer

    def get_queryset(self):
        from analytics.models import SearchDocument

        queryset = SearchDocument.objects.select_related("site").order_by("-updated_at")
        site_id = self.request.query_params.get("site")
        index_name = self.request.query_params.get("index")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if index_name:
            queryset = queryset.filter(index_name=index_name)
        return self.filter_by_site_permission(queryset)


class AnalyticsIngestView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, site_slug: str):
        site = get_object_or_404(Site, slug=site_slug)
        serializer = AnalyticsIngestSerializer(data=request.data if isinstance(request.data, dict) else {})
        serializer.is_valid(raise_exception=True)
        event, outcome = ingest_analytics_event(site=site, payload=serializer.validated_data, request=request)
        if not outcome.get("accepted", False):
            return Response({"accepted": False, "reason": outcome.get("reason", "ignored")}, status=status.HTTP_202_ACCEPTED)
        return Response(
            {
                "accepted": True,
                "event_id": outcome.get("event_id"),
                "session_key": outcome.get("session_key"),
                "site": site.slug,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class AnalyticsSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, site_id: int):
        site = get_object_or_404(Site, pk=site_id)
        if not has_site_permission(request.user, site, SitePermission.ANALYTICS):
            return Response({"detail": "You don't have analytics access for this site."}, status=status.HTTP_403_FORBIDDEN)
        query_serializer = AnalyticsSummaryQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        payload = analytics_summary(
            site=site,
            period=query_serializer.validated_data["period"],
            days=query_serializer.validated_data["days"],
            include_bots=query_serializer.validated_data["include_bots"],
        )
        payload["site"] = {"id": site.id, "slug": site.slug}
        return Response(payload)


class AnalyticsFunnelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, site_id: int):
        site = get_object_or_404(Site, pk=site_id)
        if not has_site_permission(request.user, site, SitePermission.ANALYTICS):
            return Response({"detail": "You don't have analytics access for this site."}, status=status.HTTP_403_FORBIDDEN)
        steps = request.data.get("steps") if isinstance(request.data, dict) else []
        if not isinstance(steps, list) or not steps:
            return Response({"detail": "steps must be a non-empty array."}, status=status.HTTP_400_BAD_REQUEST)
        cleaned_steps = [str(step).strip()[:120] for step in steps if str(step).strip()]
        if not cleaned_steps:
            return Response({"detail": "steps must contain non-empty values."}, status=status.HTTP_400_BAD_REQUEST)
        days = request.data.get("days", 30)
        try:
            days = int(days)
        except (TypeError, ValueError):
            return Response({"detail": "days must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        payload = analytics_funnel(site=site, steps=cleaned_steps, days=days)
        payload["site"] = {"id": site.id, "slug": site.slug}
        return Response(payload)


__all__ = [
    "AnalyticsEventViewSet",
    "AnalyticsFunnelView",
    "AnalyticsIngestView",
    "AnalyticsSessionViewSet",
    "AnalyticsSummaryView",
    "CommerceAnalyticsEventViewSet",
    "SearchDocumentViewSet",
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
