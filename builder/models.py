from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Site(TimeStampedModel):
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    tagline = models.CharField(max_length=180, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    theme = models.JSONField(default=dict, blank=True)
    navigation = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    workspace = models.ForeignKey(
        "Workspace",
        related_name="sites",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            from .localization import ensure_site_locale

            localization = (self.settings or {}).get("localization") or {}
            default_locale = localization.get("default_locale") or "en"
            if not self.locales.exists():
                ensure_site_locale(self, default_locale, is_default=True)

    def __str__(self) -> str:
        return self.name


class SiteLocale(TimeStampedModel):
    DIRECTION_LTR = "ltr"
    DIRECTION_RTL = "rtl"
    DIRECTION_CHOICES = [
        (DIRECTION_LTR, "Left to right"),
        (DIRECTION_RTL, "Right to left"),
    ]

    site = models.ForeignKey(Site, related_name="locales", on_delete=models.CASCADE)
    code = models.CharField(max_length=32)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default=DIRECTION_LTR)
    is_default = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "code"]
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="unique_site_locale_code"),
            models.UniqueConstraint(
                fields=["site"],
                condition=models.Q(is_default=True),
                name="unique_default_locale_per_site",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.code}"


class Page(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    site = models.ForeignKey(Site, related_name="pages", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    path = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_homepage = models.BooleanField(default=False)
    seo = models.JSONField(default=dict, blank=True)
    page_settings = models.JSONField(default=dict, blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="Schedule publish time")

    class Meta:
        ordering = ["-is_homepage", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "path"], name="unique_site_path"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class PageTranslation(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    page = models.ForeignKey(Page, related_name="translations", on_delete=models.CASCADE)
    locale = models.ForeignKey(SiteLocale, related_name="page_translations", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    path = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    seo = models.JSONField(default=dict, blank=True)
    page_settings = models.JSONField(default=dict, blank=True)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["locale__code", "title"]
        constraints = [
            models.UniqueConstraint(fields=["page", "locale"], name="unique_page_locale_translation"),
            models.UniqueConstraint(fields=["locale", "path"], name="unique_locale_translation_path"),
        ]

    def __str__(self) -> str:
        return f"{self.page.title} [{self.locale.code}]"


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


class PostCategory(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="post_categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_post_category_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class PostTag(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="post_tags", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_post_tag_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class ProductCategory(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="product_categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_product_category_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class Product(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    site = models.ForeignKey(Site, related_name="products", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    description_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        "MediaAsset",
        related_name="product_featured_for",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(ProductCategory, related_name="products", blank=True)
    seo = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-is_featured", "-published_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_product_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, related_name="variants", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    sku = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    inventory = models.IntegerField(default=0)
    track_inventory = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-is_default", "title"]
        constraints = [
            models.UniqueConstraint(fields=["product", "sku"], name="unique_product_variant_sku"),
        ]

    def __str__(self) -> str:
        return f"{self.product.title}: {self.title}"


class Cart(TimeStampedModel):
    STATUS_OPEN = "open"
    STATUS_CONVERTED = "converted"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CONVERTED, "Converted"),
        (STATUS_ABANDONED, "Abandoned"),
    ]

    site = models.ForeignKey(Site, related_name="carts", on_delete=models.CASCADE)
    session_key = models.CharField(max_length=80)
    currency = models.CharField(max_length=8, default="USD")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    converted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "session_key"],
                condition=models.Q(status="open"),
                name="unique_open_cart_for_session",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.session_key} ({self.status})"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product_variant = models.ForeignKey(ProductVariant, related_name="cart_items", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product_variant"], name="unique_cart_variant"),
        ]

    def __str__(self) -> str:
        return f"{self.cart.site.name}: {self.product_variant.title} x {self.quantity}"


class Order(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FULFILLED = "fulfilled"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FULFILLED, "Fulfilled"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PAYMENT_PENDING = "pending"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"
    PAYMENT_REFUNDED = "refunded"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    ]

    site = models.ForeignKey(Site, related_name="orders", on_delete=models.CASCADE)
    order_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING)
    currency = models.CharField(max_length=8, default="USD")
    customer_name = models.CharField(max_length=180)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=40, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)
    shipping_address = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pricing_details = models.JSONField(default=dict, blank=True)
    payment_provider = models.CharField(max_length=80, blank=True)
    payment_reference = models.CharField(max_length=180, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-placed_at"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.order_number}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="order_items", on_delete=models.SET_NULL, null=True, blank=True)
    product_variant = models.ForeignKey(
        ProductVariant,
        related_name="order_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180)
    sku = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.order.order_number}: {self.title}"


class Post(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    site = models.ForeignKey(Site, related_name="posts", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    body_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        MediaAsset,
        related_name="featured_posts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(PostCategory, related_name="posts", blank=True)
    tags = models.ManyToManyField(PostTag, related_name="posts", blank=True)
    seo = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="Schedule publish time")

    class Meta:
        ordering = ["-published_at", "-updated_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_post_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class Comment(TimeStampedModel):
    post = models.ForeignKey(Post, related_name="comments", on_delete=models.CASCADE)
    author_name = models.CharField(max_length=140)
    author_email = models.EmailField()
    body = models.TextField()
    is_approved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.post.title}: {self.author_name}"


class FormSubmission(TimeStampedModel):
    STATUS_NEW = "new"
    STATUS_REVIEWED = "reviewed"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="form_submissions", on_delete=models.CASCADE)
    page = models.ForeignKey(Page, related_name="form_submissions", on_delete=models.SET_NULL, null=True, blank=True)
    form_name = models.CharField(max_length=140)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.form_name}"


class Form(TimeStampedModel):
    """Reusable form definition with field schema."""

    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="forms", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    # Form schema - list of field definitions
    # Each field: {id, type, label, name, placeholder, required, options, validation}
    fields = models.JSONField(default=list, blank=True)

    # Form settings
    submit_button_text = models.CharField(max_length=60, default="Submit")
    success_message = models.TextField(default="Thank you for your submission!")
    redirect_url = models.URLField(max_length=500, blank=True)
    notify_emails = models.JSONField(default=list, blank=True)  # List of emails to notify

    # Spam protection
    enable_captcha = models.BooleanField(default=False)
    honeypot_field = models.CharField(max_length=60, default="website")

    # Styling
    form_class = models.CharField(max_length=255, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="unique_site_form_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


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
            models.UniqueConstraint(fields=["site", "page", "date", "source"], name="unique_seo_analytics_entry"),
        ]

    def __str__(self) -> str:
        page_name = self.page.title if self.page else "Site-wide"
        return f"{self.site.name} - {page_name}: {self.date}"


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
            models.UniqueConstraint(fields=["site", "keyword"], name="unique_site_keyword"),
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
            models.UniqueConstraint(fields=["keyword", "date", "source"], name="unique_keyword_rank_entry"),
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


# ---------------------------------------------------------------------------
# Workspace / Team / Membership Models
# ---------------------------------------------------------------------------

class Workspace(TimeStampedModel):
    """A workspace groups sites and members together for access control."""

    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        "auth.User",
        related_name="owned_workspaces",
        on_delete=models.CASCADE,
    )
    settings = models.JSONField(default=dict, blank=True)
    is_personal = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceMembership(TimeStampedModel):
    """Membership linking users to workspaces with roles."""

    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_EDITOR = "editor"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_VIEWER, "Viewer"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="memberships", on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", related_name="workspace_memberships", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    invited_by = models.ForeignKey(
        "auth.User",
        related_name="sent_invitations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["role", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_workspace_user"),
        ]

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.user.username} ({self.role})"

    @property
    def can_manage_members(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN)

    @property
    def can_edit_content(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_EDITOR)

    @property
    def can_view_content(self) -> bool:
        return True  # All roles can view


class WorkspaceInvitation(TimeStampedModel):
    """Pending invitation to join a workspace."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_EXPIRED, "Expired"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="invitations", on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=WorkspaceMembership.ROLE_CHOICES, default=WorkspaceMembership.ROLE_EDITOR)
    token = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    invited_by = models.ForeignKey("auth.User", related_name="workspace_invitations", on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.email} ({self.status})"


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


from .models_commerce_pro import DiscountCode, ShippingRate, ShippingZone, TaxRate  # noqa: E402
from .models_platform_admin import PlatformEmailCampaign, PlatformOffer, PlatformSubscription  # noqa: E402
