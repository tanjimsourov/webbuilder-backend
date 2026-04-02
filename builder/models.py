import uuid
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings

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
from cms.models import Page, PageTranslation  # noqa: F401
from forms.models import Form, FormSubmission  # noqa: F401


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
    snapshot = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.page.title}: {self.label}"


class MediaAsset(TimeStampedModel):
    KIND_IMAGE = "image"
    KIND_DOCUMENT = "document"
    KIND_VIDEO = "video"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_IMAGE, "Image"),
        (KIND_DOCUMENT, "Document"),
        (KIND_VIDEO, "Video"),
        (KIND_OTHER, "Other"),
    ]

    site = models.ForeignKey(Site, related_name="media_assets", on_delete=models.CASCADE)
    folder = models.ForeignKey("MediaFolder", related_name="assets", on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=180)
    file = models.FileField(upload_to="uploads/%Y/%m/")
    alt_text = models.CharField(max_length=255, blank=True)
    caption = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class BlockTemplate(TimeStampedModel):
    CATEGORY_HERO = "hero"
    CATEGORY_FEATURE = "feature"
    CATEGORY_CTA = "cta"
    CATEGORY_TESTIMONIAL = "testimonial"
    CATEGORY_PRICING = "pricing"
    CATEGORY_FAQ = "faq"
    CATEGORY_FOOTER = "footer"
    CATEGORY_HEADER = "header"
    CATEGORY_CONTENT = "content"
    CATEGORY_GALLERY = "gallery"
    CATEGORY_FORM = "form"
    CATEGORY_OTHER = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_HERO, "Hero"),
        (CATEGORY_FEATURE, "Feature"),
        (CATEGORY_CTA, "Call to Action"),
        (CATEGORY_TESTIMONIAL, "Testimonial"),
        (CATEGORY_PRICING, "Pricing"),
        (CATEGORY_FAQ, "FAQ"),
        (CATEGORY_FOOTER, "Footer"),
        (CATEGORY_HEADER, "Header"),
        (CATEGORY_CONTENT, "Content"),
        (CATEGORY_GALLERY, "Gallery"),
        (CATEGORY_FORM, "Form"),
        (CATEGORY_OTHER, "Other"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_MARKETPLACE = "marketplace"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_MARKETPLACE, "Marketplace"),
        (STATUS_DISABLED, "Disabled"),
    ]

    PLAN_FREE = "free"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_FREE, "Free"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]

    site = models.ForeignKey(Site, related_name="block_templates", on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=180)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER)
    description = models.TextField(blank=True)
    thumbnail_url = models.URLField(blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    is_global = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    usage_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED)
    tags = models.JSONField(default=list, blank=True)
    plan_required = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_FREE)
    author = models.CharField(max_length=140, blank=True)
    preview_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-is_global", "-usage_count", "name"]

    def __str__(self) -> str:
        prefix = "Global" if self.is_global else (self.site.name if self.site else "Orphan")
        return f"{prefix}: {self.name}"


class URLRedirect(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    TYPE_PERMANENT = "301"
    TYPE_TEMPORARY = "302"
    TYPE_CHOICES = [
        (TYPE_PERMANENT, "301 Permanent"),
        (TYPE_TEMPORARY, "302 Temporary"),
    ]

    site = models.ForeignKey(Site, related_name="redirects", on_delete=models.CASCADE)
    source_path = models.CharField(max_length=500)
    target_path = models.CharField(max_length=500)
    redirect_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_PERMANENT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    hit_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["site", "source_path"]
        constraints = [
            models.UniqueConstraint(fields=["site", "source_path"], name="unique_site_redirect_source"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.source_path} → {self.target_path}"


class DomainContact(TimeStampedModel):
    ROLE_REGISTRANT = "registrant"
    ROLE_ADMIN = "admin"
    ROLE_TECH = "tech"
    ROLE_BILLING = "billing"
    ROLE_CHOICES = [
        (ROLE_REGISTRANT, "Registrant"),
        (ROLE_ADMIN, "Administrative"),
        (ROLE_TECH, "Technical"),
        (ROLE_BILLING, "Billing"),
    ]

    site = models.ForeignKey(Site, related_name="domain_contacts", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_REGISTRANT)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    organization = models.CharField(max_length=140, blank=True)
    address1 = models.CharField(max_length=255, blank=True)
    address2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2 country code")

    class Meta:
        ordering = ["role", "last_name"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.first_name} {self.last_name} ({self.role})"


class Domain(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending Verification"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_FAILED, "Verification Failed"),
    ]

    REG_STATUS_UNREGISTERED = "unregistered"
    REG_STATUS_ACTIVE = "active"
    REG_STATUS_EXPIRED = "expired"
    REG_STATUS_PENDING_TRANSFER = "pending_transfer"
    REG_STATUS_PENDING_DELETE = "pending_delete"
    REG_STATUS_LOCKED = "locked"
    REG_STATUS_CHOICES = [
        (REG_STATUS_UNREGISTERED, "Unregistered / External"),
        (REG_STATUS_ACTIVE, "Active"),
        (REG_STATUS_EXPIRED, "Expired"),
        (REG_STATUS_PENDING_TRANSFER, "Pending Transfer"),
        (REG_STATUS_PENDING_DELETE, "Pending Delete"),
        (REG_STATUS_LOCKED, "Locked"),
    ]

    VERIFY_METHOD_DNS_TXT = "dns_txt"
    VERIFY_METHOD_FILE = "file"
    VERIFY_METHOD_CHOICES = [
        (VERIFY_METHOD_DNS_TXT, "DNS TXT Record"),
        (VERIFY_METHOD_FILE, "File Upload"),
    ]

    site = models.ForeignKey(Site, related_name="domains", on_delete=models.CASCADE)
    domain_name = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(default=False)

    # Verification
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    verification_token = models.CharField(max_length=100, blank=True)
    verification_method = models.CharField(
        max_length=40, choices=VERIFY_METHOD_CHOICES, default=VERIFY_METHOD_DNS_TXT, blank=True
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    last_verification_attempt = models.DateTimeField(blank=True, null=True)
    verification_error = models.TextField(blank=True)

    # Registration / portfolio
    registration_status = models.CharField(
        max_length=30, choices=REG_STATUS_CHOICES, default=REG_STATUS_UNREGISTERED
    )
    registrar = models.CharField(max_length=140, blank=True)
    registrar_account = models.CharField(max_length=140, blank=True)
    registered_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    auto_renew = models.BooleanField(default=True)
    privacy_enabled = models.BooleanField(default=False)
    transfer_lock = models.BooleanField(default=True)
    auth_code = models.CharField(max_length=255, blank=True)

    # SSL / TLS
    ssl_enabled = models.BooleanField(default=False)
    ssl_expires_at = models.DateTimeField(blank=True, null=True)

    # DNS
    dns_records = models.JSONField(default=list, blank=True)
    nameservers = models.JSONField(default=list, blank=True)

    # WHOIS cache
    whois_data = models.JSONField(default=dict, blank=True)
    whois_fetched_at = models.DateTimeField(blank=True, null=True)

    # Notes / tags (portfolio management)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)

    # Linked contact
    registrant_contact = models.ForeignKey(
        DomainContact,
        related_name="domains_as_registrant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-is_primary", "domain_name"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.domain_name}"


class DomainAvailability(models.Model):
    domain_name = models.CharField(max_length=255)
    available = models.BooleanField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="USD", blank=True)
    registrar = models.CharField(max_length=140, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["domain_name", "checked_at"]),
        ]

    def __str__(self) -> str:
        status = "available" if self.available else "taken"
        return f"{self.domain_name}: {status}"


class MediaFolder(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="media_folders", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    parent = models.ForeignKey("self", related_name="subfolders", on_delete=models.CASCADE, null=True, blank=True)
    path = models.CharField(max_length=500)

    class Meta:
        ordering = ["path", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "path"], name="unique_site_folder_path"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.path}"


class NavigationMenu(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="navigation_menus", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160)
    location = models.CharField(max_length=60, default="header")
    items = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["location", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_menu_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class Webhook(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    EVENT_PAGE_PUBLISHED = "page.published"
    EVENT_POST_PUBLISHED = "post.published"
    EVENT_PRODUCT_PUBLISHED = "product.published"
    EVENT_ORDER_CREATED = "order.created"
    EVENT_FORM_SUBMITTED = "form.submitted"
    EVENT_CHOICES = [
        (EVENT_PAGE_PUBLISHED, "Page Published"),
        (EVENT_POST_PUBLISHED, "Post Published"),
        (EVENT_PRODUCT_PUBLISHED, "Product Published"),
        (EVENT_ORDER_CREATED, "Order Created"),
        (EVENT_FORM_SUBMITTED, "Form Submitted"),
    ]

    site = models.ForeignKey(Site, related_name="webhooks", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    url = models.URLField(max_length=500)
    event = models.CharField(max_length=60, choices=EVENT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    secret = models.CharField(max_length=100, blank=True)
    last_triggered_at = models.DateTimeField(blank=True, null=True)
    success_count = models.IntegerField(default=0)
    failure_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["event", "name"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name} ({self.event})"


class RobotsTxt(TimeStampedModel):
    site = models.OneToOneField(Site, related_name="robots_txt", on_delete=models.CASCADE)
    content = models.TextField(default="User-agent: *\nAllow: /")
    is_custom = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Robots.txt"
        verbose_name_plural = "Robots.txt"

    def __str__(self) -> str:
        return f"{self.site.name}: robots.txt"


# ---------------------------------------------------------------------------
# Background Jobs Models
# ---------------------------------------------------------------------------

class Job(TimeStampedModel):
    """A background job to be executed."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PRIORITY_LOW = 0
    PRIORITY_NORMAL = 5
    PRIORITY_HIGH = 10
    PRIORITY_URGENT = 20

    job_type = models.CharField(max_length=100)
    job_id = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    priority = models.IntegerField(default=PRIORITY_NORMAL)
    scheduled_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    max_retries = models.IntegerField(default=3)
    retry_count = models.IntegerField(default=0)
    retry_delay_seconds = models.IntegerField(default=60)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-priority", "scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["job_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.job_type}: {self.job_id} ({self.status})"


class WebhookDelivery(TimeStampedModel):
    """Track webhook delivery attempts."""

    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]

    webhook = models.ForeignKey(Webhook, related_name="deliveries", on_delete=models.CASCADE)
    event = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=5)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.webhook.name}: {self.event} ({self.status})"


# Email Hosting Models

class EmailDomain(TimeStampedModel):
    """Email domain associated with a site/workspace."""
    
    class DomainStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        VERIFYING = 'verifying', 'Verifying'
        ACTIVE = 'active', 'Active'
        FAILED = 'failed', 'Failed'
        SUSPENDED = 'suspended', 'Suspended'

    site = models.ForeignKey(
        Site,
        related_name='email_domains',
        on_delete=models.CASCADE,
        help_text='Site that owns this email domain',
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name='email_domains',
        on_delete=models.CASCADE,
        help_text='Workspace that owns this domain',
    )
    name = models.CharField(
        max_length=253,
        unique=True,
        help_text='Fully qualified domain name for email hosting',
    )
    status = models.CharField(
        max_length=20,
        choices=DomainStatus.choices,
        default=DomainStatus.PENDING,
        help_text='Current verification state of the email domain',
    )
    verification_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        help_text='Token used for DNS verification',
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp when domain was verified',
    )
    mx_record = models.CharField(
        max_length=255,
        blank=True,
        help_text='MX record for email routing',
    )
    spf_record = models.TextField(
        blank=True,
        help_text='SPF record for email authentication',
    )
    dkim_record = models.TextField(
        blank=True,
        help_text='DKIM record for email signing',
    )
    dmarc_record = models.TextField(
        blank=True,
        help_text='DMARC record for email policy',
    )

    class Meta:
        ordering = ['name']
        unique_together = ('site', 'name')

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class Mailbox(TimeStampedModel):
    """Email mailbox within a domain."""
    
    workspace = models.ForeignKey(
        Workspace,
        related_name='mailboxes',
        on_delete=models.CASCADE,
    )
    site = models.ForeignKey(
        Site,
        related_name='mailboxes',
        on_delete=models.CASCADE,
    )
    domain = models.ForeignKey(
        EmailDomain,
        related_name='mailboxes',
        on_delete=models.CASCADE,
    )
    local_part = models.CharField(
        max_length=64,
        help_text='Username part before @',
    )
    password_hash = models.CharField(
        max_length=128,
        help_text='Hashed password for authentication',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether mailbox is active',
    )
    quota_mb = models.PositiveIntegerField(
        default=1024,
        help_text='Storage quota in megabytes',
    )
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Last successful login timestamp',
    )
    user = models.ForeignKey(
        get_user_model(),
        related_name='mailboxes',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text='Associated user account',
    )

    class Meta:
        ordering = ['local_part']
        unique_together = ('domain', 'local_part')

    @property
    def email_address(self) -> str:
        return f"{self.local_part}@{self.domain.name}"

    def __str__(self) -> str:
        return self.email_address


class MailAlias(TimeStampedModel):
    """Email alias that forwards to a mailbox."""
    
    workspace = models.ForeignKey(
        Workspace,
        related_name='mail_aliases',
        on_delete=models.CASCADE,
    )
    site = models.ForeignKey(
        Site,
        related_name='mail_aliases',
        on_delete=models.CASCADE,
    )
    source_address = models.EmailField(
        help_text='Source email address for alias',
    )
    destination_mailbox = models.ForeignKey(
        Mailbox,
        related_name='aliases',
        on_delete=models.CASCADE,
        help_text='Mailbox to forward emails to',
    )
    active = models.BooleanField(
        default=True,
        help_text='Whether alias is active',
    )

    class Meta:
        ordering = ['source_address']
        unique_together = ('source_address', 'destination_mailbox')

    def __str__(self) -> str:
        return f"{self.source_address} → {self.destination_mailbox.email_address}"


class EmailProvisioningTask(TimeStampedModel):
    """Background task for email provisioning operations."""
    
    class TaskType(models.TextChoices):
        CREATE_DOMAIN = 'create_domain', 'Create Domain'
        DELETE_DOMAIN = 'delete_domain', 'Delete Domain'
        VERIFY_DOMAIN = 'verify_domain', 'Verify Domain'
        CREATE_MAILBOX = 'create_mailbox', 'Create Mailbox'
        DELETE_MAILBOX = 'delete_mailbox', 'Delete Mailbox'
        UPDATE_MAILBOX = 'update_mailbox', 'Update Mailbox'
        CREATE_ALIAS = 'create_alias', 'Create Alias'
        DELETE_ALIAS = 'delete_alias', 'Delete Alias'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    workspace = models.ForeignKey(
        Workspace,
        related_name='email_provisioning_tasks',
        on_delete=models.CASCADE,
    )
    task_type = models.CharField(
        max_length=30,
        choices=TaskType.choices,
        help_text='Type of provisioning task',
    )
    target_id = models.CharField(
        max_length=64,
        help_text='ID of the object being provisioned',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text='Current task status',
    )
    message = models.TextField(
        blank=True,
        help_text='Task result or error message',
    )
    payload = models.JSONField(
        null=True,
        blank=True,
        help_text='Additional task data',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.task_type} ({self.status})"


from .models_platform_admin import PlatformEmailCampaign, PlatformOffer, PlatformSubscription  # noqa: E402
