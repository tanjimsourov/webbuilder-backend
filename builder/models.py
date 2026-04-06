from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from analytics.models import (  # noqa: F401
    KeywordRankEntry,
    SEOAnalytics,
    SEOAudit,
    SEOSettings,
    SearchConsoleCredential,
    TrackedKeyword,
)
from blog.models import Comment, Post, PostCategory, PostTag  # noqa: F401
from commerce.models import (  # noqa: F401
    Cart,
    CartItem,
    DiscountCode,
    Order,
    OrderItem,
    Product,
    ProductCategory,
    ProductVariant,
    ShippingRate,
    ShippingZone,
    TaxRate,
)
from core.models import Site, SiteLocale, TimeStampedModel, Workspace, WorkspaceInvitation, WorkspaceMembership  # noqa: F401
from cms.models import (  # noqa: F401
    BlockTemplate,
    MediaAsset,
    MediaFolder,
    NavigationMenu,
    Page,
    PageTranslation,
    RobotsTxt,
    URLRedirect,
)
from cms.page_schema import PAGE_SCHEMA_VERSION
from domains.models import Domain, DomainAvailability, DomainContact  # noqa: F401
from forms.models import Form, FormSubmission  # noqa: F401
from jobs.models import Job  # noqa: F401
from notifications.models import Webhook, WebhookDelivery  # noqa: F401
from email_hosting.models import EmailDomain, EmailProvisioningTask, MailAlias, Mailbox  # noqa: F401

class PageExperiment(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="page_experiments", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="experiments", on_delete=models.CASCADE)
    locale = models.ForeignKey(
        SiteLocale,
        related_name="experiments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=180)
    key = models.SlugField(max_length=80)
    hypothesis = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    coverage_percent = models.PositiveSmallIntegerField(
        default=100,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    goal_form_name = models.CharField(max_length=140, blank=True)
    audience = models.JSONField(default=dict, blank=True)
    starts_at = models.DateTimeField(blank=True, null=True)
    ends_at = models.DateTimeField(blank=True, null=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["page__title", "-updated_at", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "key"], name="unique_site_page_experiment_key"),
        ]
        indexes = [
            models.Index(fields=["site", "page", "status"]),
            models.Index(fields=["page", "locale", "status"]),
        ]

    def __str__(self) -> str:
        scope = self.locale.code if self.locale_id else "default"
        return f"{self.site.name}: {self.name} [{scope}]"


class PageExperimentVariant(TimeStampedModel):
    experiment = models.ForeignKey(PageExperiment, related_name="variants", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    key = models.SlugField(max_length=80)
    description = models.CharField(max_length=280, blank=True)
    is_control = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    weight = models.PositiveIntegerField(default=50)
    title = models.CharField(max_length=180, blank=True)
    seo = models.JSONField(default=dict, blank=True)
    page_settings = models.JSONField(default=dict, blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)

    class Meta:
        ordering = ["-is_control", "name"]
        constraints = [
            models.UniqueConstraint(fields=["experiment", "key"], name="unique_experiment_variant_key"),
        ]

    def __str__(self) -> str:
        return f"{self.experiment.name}: {self.name}"


class ExperimentEvent(TimeStampedModel):
    EVENT_EXPOSURE = "exposure"
    EVENT_CONVERSION = "conversion"
    EVENT_CHOICES = [
        (EVENT_EXPOSURE, "Exposure"),
        (EVENT_CONVERSION, "Conversion"),
    ]

    experiment = models.ForeignKey(PageExperiment, related_name="events", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        PageExperimentVariant,
        related_name="events",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="experiment_events", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="experiment_events", on_delete=models.SET_NULL, null=True, blank=True)
    locale_code = models.CharField(max_length=32, blank=True)
    visitor_id = models.CharField(max_length=64)
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    goal_key = models.CharField(max_length=140, blank=True)
    request_path = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "visitor_id", "event_type", "goal_key"],
                name="unique_experiment_event_per_goal",
            ),
        ]
        indexes = [
            models.Index(fields=["site", "page", "event_type"]),
            models.Index(fields=["experiment", "event_type", "created_at"]),
            models.Index(fields=["visitor_id", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.experiment.name}: {self.event_type} ({self.visitor_id})"


class PageReview(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_IN_REVIEW = "in_review"
    STATUS_CHANGES_REQUESTED = "changes_requested"
    STATUS_APPROVED = "approved"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_IN_REVIEW, "In review"),
        (STATUS_CHANGES_REQUESTED, "Changes requested"),
        (STATUS_APPROVED, "Approved"),
    ]

    page = models.ForeignKey(Page, related_name="reviews", on_delete=models.CASCADE)
    locale = models.ForeignKey(
        SiteLocale,
        related_name="page_reviews",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    title = models.CharField(max_length=180, blank=True)
    last_note = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        "auth.User",
        related_name="requested_page_reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    assigned_to = models.ForeignKey(
        "auth.User",
        related_name="assigned_page_reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        "auth.User",
        related_name="approved_page_reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    requested_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["page__title", "-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["page", "locale"], name="unique_page_review_per_locale"),
            models.UniqueConstraint(
                fields=["page"],
                condition=models.Q(locale__isnull=True),
                name="unique_default_page_review",
            ),
        ]
        indexes = [
            models.Index(fields=["page", "status"]),
            models.Index(fields=["assigned_to", "status"]),
        ]

    def __str__(self) -> str:
        scope = self.locale.code if self.locale_id else "default"
        return f"{self.page.title} review [{scope}]"


class PageReviewComment(TimeStampedModel):
    review = models.ForeignKey(PageReview, related_name="comments", on_delete=models.CASCADE)
    parent = models.ForeignKey(
        "self",
        related_name="replies",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    author = models.ForeignKey(
        "auth.User",
        related_name="page_review_comments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    body = models.TextField()
    mentions = models.JSONField(default=list, blank=True)
    anchor = models.JSONField(default=dict, blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "auth.User",
        related_name="resolved_page_review_comments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["review", "is_resolved"]),
            models.Index(fields=["author", "created_at"]),
        ]

    def __str__(self) -> str:
        author_label = self.author.username if self.author_id else "Unknown"
        return f"{self.review}: {author_label}"


class PageRevision(models.Model):
    page = models.ForeignKey(Page, related_name="revisions", on_delete=models.CASCADE)
    label = models.CharField(max_length=180)
    builder_schema_version = models.PositiveSmallIntegerField(default=PAGE_SCHEMA_VERSION)
    snapshot = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.page.title}: {self.label}"

# Moved models are imported above for backwards compatibility.

from .models_platform_admin import PlatformEmailCampaign, PlatformOffer, PlatformSubscription  # noqa: E402
