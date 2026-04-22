"""Analytics app models."""

from __future__ import annotations

import uuid

from django.db import models

from cms.models import Page
from core.models import Site, TimeStampedModel


class SEOAnalytics(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="seo_analytics", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="seo_analytics", on_delete=models.CASCADE, null=True, blank=True)
    date = models.DateField()
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    average_position = models.FloatField(default=0.0)
    ctr = models.FloatField(default=0.0)
    source = models.CharField(max_length=40, default="google_search_console")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "page", "date", "source"],
                name="analytics_unique_seo_analytics_entry",
            ),
        ]

    def __str__(self) -> str:
        page_name = self.page.title if self.page else "Site-wide"
        return f"{self.site.name} - {page_name}: {self.date}"


class SearchConsoleCredential(TimeStampedModel):
    """Stores encrypted OAuth2 tokens for Google Search Console per site."""

    site = models.OneToOneField(Site, related_name="gsc_credential", on_delete=models.CASCADE)
    property_url = models.CharField(max_length=500, blank=True)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expiry = models.DateTimeField(blank=True, null=True)
    scopes = models.JSONField(default=list, blank=True)
    last_synced_at = models.DateTimeField(blank=True, null=True)
    sync_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Search Console Credential"

    def __str__(self) -> str:
        return f"{self.site.name}: GSC ({self.property_url or 'unconfigured'})"


class SEOAudit(TimeStampedModel):
    """Technical SEO audit snapshot for a single page."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_ERROR, "Error"),
    ]

    site = models.ForeignKey(Site, related_name="seo_audits", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="seo_audits", on_delete=models.CASCADE, null=True, blank=True)
    audited_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    score = models.IntegerField(default=0)

    # On-page checks
    title = models.CharField(max_length=500, blank=True)
    title_length = models.IntegerField(default=0)
    meta_description = models.CharField(max_length=1000, blank=True)
    meta_description_length = models.IntegerField(default=0)
    h1_count = models.IntegerField(default=0)
    h1_text = models.TextField(blank=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    og_title = models.CharField(max_length=500, blank=True)
    og_description = models.CharField(max_length=1000, blank=True)
    og_image = models.URLField(max_length=1000, blank=True)

    # Technical checks
    response_time_ms = models.IntegerField(default=0)
    status_code = models.IntegerField(default=0)
    word_count = models.IntegerField(default=0)
    image_count = models.IntegerField(default=0)
    images_missing_alt = models.IntegerField(default=0)
    internal_links = models.IntegerField(default=0)
    external_links = models.IntegerField(default=0)
    has_schema_markup = models.BooleanField(default=False)
    is_mobile_friendly = models.BooleanField(default=False)

    issues = models.JSONField(default=list, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        label = self.page.title if self.page else self.audited_url
        return f"{self.site.name}: {label} (score {self.score})"


class TrackedKeyword(TimeStampedModel):
    """A keyword the user wants to track rankings for."""

    site = models.ForeignKey(Site, related_name="tracked_keywords", on_delete=models.CASCADE)
    keyword = models.CharField(max_length=255)
    target_url = models.CharField(max_length=1000, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["keyword"]
        constraints = [
            models.UniqueConstraint(fields=["site", "keyword"], name="analytics_unique_site_keyword"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.keyword}"


class KeywordRankEntry(models.Model):
    """A single rank data point for a tracked keyword."""

    keyword = models.ForeignKey(TrackedKeyword, related_name="rank_entries", on_delete=models.CASCADE)
    date = models.DateField()
    position = models.FloatField(null=True, blank=True)
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    url = models.CharField(max_length=1000, blank=True)
    source = models.CharField(max_length=40, default="manual")

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["keyword", "date", "source"],
                name="analytics_unique_keyword_rank_entry",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.keyword.keyword}: pos {self.position} on {self.date}"


class SEOSettings(TimeStampedModel):
    """Per-site SEO configuration."""

    SCHEDULE_DAILY = "daily"
    SCHEDULE_WEEKLY = "weekly"
    SCHEDULE_MANUAL = "manual"
    SCHEDULE_CHOICES = [
        (SCHEDULE_DAILY, "Daily"),
        (SCHEDULE_WEEKLY, "Weekly"),
        (SCHEDULE_MANUAL, "Manual only"),
    ]

    site = models.OneToOneField(Site, related_name="seo_settings", on_delete=models.CASCADE)
    audit_schedule = models.CharField(max_length=20, choices=SCHEDULE_CHOICES, default=SCHEDULE_MANUAL)
    alert_score_threshold = models.IntegerField(default=60)
    gsc_property_url = models.CharField(max_length=500, blank=True)
    sitemap_url = models.CharField(max_length=1000, blank=True)
    notify_on_issues = models.BooleanField(default=False)

    class Meta:
        verbose_name = "SEO Settings"
        verbose_name_plural = "SEO Settings"

    def __str__(self) -> str:
        return f"{self.site.name}: SEO settings"


class AnalyticsSession(TimeStampedModel):
    DEVICE_DESKTOP = "desktop"
    DEVICE_MOBILE = "mobile"
    DEVICE_TABLET = "tablet"
    DEVICE_BOT = "bot"
    DEVICE_UNKNOWN = "unknown"
    DEVICE_CHOICES = [
        (DEVICE_DESKTOP, "Desktop"),
        (DEVICE_MOBILE, "Mobile"),
        (DEVICE_TABLET, "Tablet"),
        (DEVICE_BOT, "Bot"),
        (DEVICE_UNKNOWN, "Unknown"),
    ]

    site = models.ForeignKey(Site, related_name="analytics_sessions", on_delete=models.CASCADE)
    session_key = models.CharField(max_length=64, default=uuid.uuid4, db_index=True)
    started_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    landing_path = models.CharField(max_length=255, blank=True)
    exit_path = models.CharField(max_length=255, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    referrer_domain = models.CharField(max_length=255, blank=True)
    utm_source = models.CharField(max_length=120, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=120, blank=True)
    device_type = models.CharField(max_length=20, choices=DEVICE_CHOICES, default=DEVICE_UNKNOWN)
    browser = models.CharField(max_length=120, blank=True)
    os = models.CharField(max_length=120, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    ip_prefix = models.CharField(max_length=64, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    is_bot = models.BooleanField(default=False)
    page_view_count = models.PositiveIntegerField(default=0)
    event_count = models.PositiveIntegerField(default=0)
    conversion_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "analytics_sessions"
        ordering = ["-last_seen_at"]
        constraints = [
            models.UniqueConstraint(fields=["site", "session_key"], name="analytics_unique_site_session_key"),
        ]
        indexes = [
            models.Index(fields=["site", "last_seen_at"]),
            models.Index(fields=["site", "is_bot", "last_seen_at"]),
            models.Index(fields=["site", "started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: session {self.session_key}"


class AnalyticsEvent(TimeStampedModel):
    TYPE_PAGE_VIEW = "page_view"
    TYPE_EVENT = "event"
    TYPE_CONVERSION = "conversion"
    TYPE_FUNNEL = "funnel"
    TYPE_CHOICES = [
        (TYPE_PAGE_VIEW, "Page view"),
        (TYPE_EVENT, "Event"),
        (TYPE_CONVERSION, "Conversion"),
        (TYPE_FUNNEL, "Funnel"),
    ]

    site = models.ForeignKey(Site, related_name="analytics_events", on_delete=models.CASCADE)
    session = models.ForeignKey(
        AnalyticsSession,
        related_name="events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    event_name = models.CharField(max_length=120, default="page_view")
    event_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_EVENT)
    path = models.CharField(max_length=255, blank=True)
    title = models.CharField(max_length=255, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    referrer_domain = models.CharField(max_length=255, blank=True)
    device_type = models.CharField(max_length=20, choices=AnalyticsSession.DEVICE_CHOICES, default=AnalyticsSession.DEVICE_UNKNOWN)
    browser = models.CharField(max_length=120, blank=True)
    os = models.CharField(max_length=120, blank=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_bot = models.BooleanField(default=False)
    ip_hash = models.CharField(max_length=64, blank=True)
    ip_prefix = models.CharField(max_length=64, blank=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    properties = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "analytics_events"
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["site", "event_type", "occurred_at"]),
            models.Index(fields=["site", "event_name", "occurred_at"]),
            models.Index(fields=["site", "path", "occurred_at"]),
            models.Index(fields=["session", "occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.event_name} ({self.event_type})"


class SearchDocument(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="search_documents", on_delete=models.CASCADE)
    index_name = models.CharField(max_length=60)
    external_id = models.CharField(max_length=120)
    title = models.CharField(max_length=255, blank=True)
    path = models.CharField(max_length=255, blank=True)
    content = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "search_documents"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "index_name", "external_id"],
                name="analytics_unique_search_document",
            ),
        ]
        indexes = [
            models.Index(fields=["site", "index_name", "updated_at"]),
            models.Index(fields=["site", "path"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.index_name}/{self.external_id}"


class AnalyticsRollup(TimeStampedModel):
    PERIOD_DAILY = "daily"
    PERIOD_CHOICES = [
        (PERIOD_DAILY, "Daily"),
    ]

    site = models.ForeignKey(Site, related_name="analytics_rollups", on_delete=models.CASCADE)
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=PERIOD_DAILY)
    period_date = models.DateField()
    page_views = models.PositiveIntegerField(default=0)
    events = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    sessions = models.PositiveIntegerField(default=0)
    total_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "analytics_rollups"
        ordering = ["-period_date", "site_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "period", "period_date"],
                name="analytics_unique_rollup_period",
            ),
        ]
        indexes = [
            models.Index(fields=["site", "period", "period_date"]),
            models.Index(fields=["period", "period_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.period} {self.period_date}"


class CommerceAnalyticsEvent(TimeStampedModel):
    EVENT_PRODUCT_VIEW = "product.view"
    EVENT_ADD_TO_CART = "cart.add"
    EVENT_BEGIN_CHECKOUT = "checkout.begin"
    EVENT_PURCHASE = "order.purchase"
    EVENT_REFUND = "order.refund"
    EVENT_CHOICES = [
        (EVENT_PRODUCT_VIEW, "Product view"),
        (EVENT_ADD_TO_CART, "Add to cart"),
        (EVENT_BEGIN_CHECKOUT, "Begin checkout"),
        (EVENT_PURCHASE, "Purchase"),
        (EVENT_REFUND, "Refund"),
    ]

    site = models.ForeignKey(Site, related_name="commerce_analytics_events", on_delete=models.CASCADE)
    event_name = models.CharField(max_length=60, choices=EVENT_CHOICES)
    aggregate_type = models.CharField(max_length=60, blank=True)
    aggregate_id = models.CharField(max_length=120, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "event_name", "created_at"]),
            models.Index(fields=["site", "aggregate_type", "aggregate_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.event_name}"
