"""Analytics app models."""

from __future__ import annotations

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
