from __future__ import annotations

from rest_framework import serializers

from provider.models import AIJob, AIModerationLog, AIUsageQuota, AIUsageRecord


class AIUsageQuotaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUsageQuota
        fields = [
            "id",
            "workspace",
            "site",
            "feature",
            "period",
            "max_requests",
            "max_tokens",
            "max_cost_usd",
            "reset_at",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]


class AIUsageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUsageRecord
        fields = [
            "id",
            "workspace",
            "site",
            "job",
            "actor",
            "feature",
            "provider",
            "model_name",
            "request_count",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_usd",
            "status",
            "metadata",
            "created_at",
            "updated_at",
        ]


class AIModerationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIModerationLog
        fields = [
            "id",
            "job",
            "stage",
            "blocked",
            "reasons",
            "raw_excerpt",
            "metadata",
            "created_at",
            "updated_at",
        ]


class AIJobSerializer(serializers.ModelSerializer):
    moderation_logs = AIModerationLogSerializer(many=True, read_only=True)

    class Meta:
        model = AIJob
        fields = [
            "id",
            "workspace",
            "site",
            "requested_by",
            "feature",
            "provider",
            "model_name",
            "status",
            "prompt",
            "sanitized_prompt",
            "input_payload",
            "output_payload",
            "error_message",
            "moderation_flags",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "queue_job",
            "started_at",
            "completed_at",
            "metadata",
            "moderation_logs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "sanitized_prompt",
            "output_payload",
            "error_message",
            "moderation_flags",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "queue_job",
            "started_at",
            "completed_at",
            "moderation_logs",
            "created_at",
            "updated_at",
        ]


class AIGenerationRequestSerializer(serializers.Serializer):
    site = serializers.IntegerField(required=False, min_value=1)
    workspace = serializers.IntegerField(required=False, min_value=1)
    feature = serializers.ChoiceField(
        choices=[
            AIJob.FEATURE_PAGE_OUTLINE,
            AIJob.FEATURE_BLOG_DRAFT,
            AIJob.FEATURE_PRODUCT_DESCRIPTION,
            AIJob.FEATURE_SEO_META,
            AIJob.FEATURE_IMAGE_ALT_TEXT,
            AIJob.FEATURE_FAQ_SCHEMA,
            AIJob.FEATURE_SECTION_COMPOSITION,
        ],
        required=False,
    )
    prompt = serializers.CharField(max_length=12000)
    input_payload = serializers.JSONField(required=False)
    provider = serializers.CharField(required=False, allow_blank=True, max_length=40)
    model_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    queue = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if not attrs.get("site") and not attrs.get("workspace"):
            raise serializers.ValidationError("Either site or workspace must be provided.")
        return attrs


class AIUsageSummarySerializer(serializers.Serializer):
    site = serializers.IntegerField(required=False)
    workspace = serializers.IntegerField(required=False)
    days = serializers.IntegerField(required=False, min_value=1, max_value=365, default=30)
