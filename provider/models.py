from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Site, TimeStampedModel, Workspace
from jobs.models import Job


class AIJob(TimeStampedModel):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    FEATURE_PAGE_OUTLINE = "page_outline"
    FEATURE_BLOG_DRAFT = "blog_draft"
    FEATURE_PRODUCT_DESCRIPTION = "product_description"
    FEATURE_SEO_META = "seo_meta"
    FEATURE_IMAGE_ALT_TEXT = "image_alt_text"
    FEATURE_FAQ_SCHEMA = "faq_schema"
    FEATURE_SECTION_COMPOSITION = "section_composition"
    FEATURE_CHOICES = [
        (FEATURE_PAGE_OUTLINE, "Page outline"),
        (FEATURE_BLOG_DRAFT, "Blog draft"),
        (FEATURE_PRODUCT_DESCRIPTION, "Product description"),
        (FEATURE_SEO_META, "SEO metadata"),
        (FEATURE_IMAGE_ALT_TEXT, "Image alt text"),
        (FEATURE_FAQ_SCHEMA, "FAQ schema"),
        (FEATURE_SECTION_COMPOSITION, "Section composition"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        related_name="ai_jobs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="ai_jobs", on_delete=models.SET_NULL, null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="requested_ai_jobs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    feature = models.CharField(max_length=40, choices=FEATURE_CHOICES)
    provider = models.CharField(max_length=40, default="mock")
    model_name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    prompt = models.TextField()
    sanitized_prompt = models.TextField(blank=True)
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    moderation_flags = models.JSONField(default=list, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    queue_job = models.ForeignKey(
        Job,
        related_name="ai_jobs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
            models.Index(fields=["feature", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.feature} ({self.status})"


class AIUsageQuota(TimeStampedModel):
    PERIOD_MONTHLY = "monthly"
    PERIOD_DAILY = "daily"
    PERIOD_CHOICES = [
        (PERIOD_DAILY, "Daily"),
        (PERIOD_MONTHLY, "Monthly"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        related_name="ai_usage_quotas",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="ai_usage_quotas",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    feature = models.CharField(max_length=40, default="*")
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=PERIOD_MONTHLY)
    max_requests = models.PositiveIntegerField(default=1000)
    max_tokens = models.PositiveIntegerField(default=1_000_000)
    max_cost_usd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reset_at = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "site", "feature", "period"],
                name="provider_unique_ai_quota_scope",
            ),
        ]

    def __str__(self) -> str:
        scope = f"workspace:{self.workspace_id}" if self.workspace_id else f"site:{self.site_id}"
        return f"{scope}:{self.feature}:{self.period}"


class AIUsageRecord(TimeStampedModel):
    workspace = models.ForeignKey(
        Workspace,
        related_name="ai_usage_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="ai_usage_records", on_delete=models.SET_NULL, null=True, blank=True)
    job = models.ForeignKey(AIJob, related_name="usage_records", on_delete=models.SET_NULL, null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="ai_usage_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    feature = models.CharField(max_length=40, default="")
    provider = models.CharField(max_length=40, default="mock")
    model_name = models.CharField(max_length=120, blank=True)
    request_count = models.PositiveIntegerField(default=1)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    status = models.CharField(max_length=20, default="completed")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "created_at"]),
            models.Index(fields=["site", "created_at"]),
            models.Index(fields=["feature", "created_at"]),
            models.Index(fields=["provider", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.feature} ({self.total_tokens} tokens)"


class AIModerationLog(TimeStampedModel):
    STAGE_PROMPT = "prompt"
    STAGE_OUTPUT = "output"
    STAGE_CHOICES = [
        (STAGE_PROMPT, "Prompt"),
        (STAGE_OUTPUT, "Output"),
    ]

    job = models.ForeignKey(AIJob, related_name="moderation_logs", on_delete=models.CASCADE)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    blocked = models.BooleanField(default=False)
    reasons = models.JSONField(default=list, blank=True)
    raw_excerpt = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["job", "stage", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.job_id}:{self.stage}:{'blocked' if self.blocked else 'ok'}"


def default_quota_for_scope(*, workspace, site, feature: str) -> AIUsageQuota:
    quota, _ = AIUsageQuota.objects.get_or_create(
        workspace=workspace,
        site=site,
        feature=feature,
        period=AIUsageQuota.PERIOD_MONTHLY,
        defaults={
            "max_requests": int(getattr(settings, "AI_DEFAULT_MAX_REQUESTS", 1000)),
            "max_tokens": int(getattr(settings, "AI_DEFAULT_MAX_TOKENS", 1_000_000)),
            "max_cost_usd": Decimal(str(getattr(settings, "AI_DEFAULT_MAX_COST_USD", "50.00"))),
            "reset_at": timezone.now(),
        },
    )
    return quota
