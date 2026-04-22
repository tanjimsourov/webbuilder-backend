"""Analytics domain serializers (transitional exports)."""

from __future__ import annotations

from rest_framework import serializers

from analytics.models import AnalyticsEvent, AnalyticsSession, CommerceAnalyticsEvent, SearchDocument

from builder.serializers import (  # noqa: F401
    KeywordRankEntrySerializer,
    SearchConsoleCredentialSerializer,
    SEOAnalyticsSerializer,
    SEOAuditSerializer,
    SEOSettingsSerializer,
    TrackedKeywordSerializer,
)


class CommerceAnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommerceAnalyticsEvent
        fields = [
            "id",
            "site",
            "event_name",
            "aggregate_type",
            "aggregate_id",
            "request_id",
            "payload",
            "created_at",
            "updated_at",
        ]


class AnalyticsSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsSession
        fields = [
            "id",
            "site",
            "session_key",
            "started_at",
            "last_seen_at",
            "ended_at",
            "landing_path",
            "exit_path",
            "referrer",
            "referrer_domain",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "device_type",
            "browser",
            "os",
            "is_bot",
            "page_view_count",
            "event_count",
            "conversion_count",
            "metadata",
            "created_at",
            "updated_at",
        ]


class AnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsEvent
        fields = [
            "id",
            "site",
            "session",
            "event_name",
            "event_type",
            "path",
            "title",
            "referrer",
            "referrer_domain",
            "device_type",
            "browser",
            "os",
            "value",
            "is_bot",
            "properties",
            "occurred_at",
            "created_at",
            "updated_at",
        ]


class AnalyticsIngestSerializer(serializers.Serializer):
    session_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    event_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="page_view")
    event_type = serializers.ChoiceField(
        choices=[
            AnalyticsEvent.TYPE_PAGE_VIEW,
            AnalyticsEvent.TYPE_EVENT,
            AnalyticsEvent.TYPE_CONVERSION,
            AnalyticsEvent.TYPE_FUNNEL,
        ],
        required=False,
    )
    path = serializers.CharField(max_length=255, required=False, allow_blank=True)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    referrer = serializers.CharField(max_length=500, required=False, allow_blank=True)
    value = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=0)
    occurred_at = serializers.DateTimeField(required=False)
    properties = serializers.JSONField(required=False)
    utm_source = serializers.CharField(max_length=120, required=False, allow_blank=True)
    utm_medium = serializers.CharField(max_length=120, required=False, allow_blank=True)
    utm_campaign = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate(self, attrs):
        event_name = str(attrs.get("event_name") or "").strip().lower()
        if not attrs.get("event_type"):
            if event_name in {"page_view", "pageview", "view"}:
                attrs["event_type"] = AnalyticsEvent.TYPE_PAGE_VIEW
            elif event_name in {"conversion", "purchase", "signup", "subscribe"}:
                attrs["event_type"] = AnalyticsEvent.TYPE_CONVERSION
            elif event_name.startswith("funnel."):
                attrs["event_type"] = AnalyticsEvent.TYPE_FUNNEL
            else:
                attrs["event_type"] = AnalyticsEvent.TYPE_EVENT
        return attrs


class AnalyticsSummaryQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=["daily", "weekly", "monthly"], required=False, default="daily")
    days = serializers.IntegerField(required=False, min_value=1, max_value=365, default=30)
    include_bots = serializers.BooleanField(required=False, default=False)


class SearchDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchDocument
        fields = [
            "id",
            "site",
            "index_name",
            "external_id",
            "title",
            "path",
            "content",
            "summary",
            "metadata",
            "source_updated_at",
            "created_at",
            "updated_at",
        ]


__all__ = [
    "AnalyticsEventSerializer",
    "AnalyticsIngestSerializer",
    "AnalyticsSessionSerializer",
    "AnalyticsSummaryQuerySerializer",
    "CommerceAnalyticsEventSerializer",
    "SearchDocumentSerializer",
    "KeywordRankEntrySerializer",
    "SearchConsoleCredentialSerializer",
    "SEOAnalyticsSerializer",
    "SEOAuditSerializer",
    "SEOSettingsSerializer",
    "TrackedKeywordSerializer",
]
