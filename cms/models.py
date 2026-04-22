from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import Site, SiteLocale, TimeStampedModel
from cms.page_schema import PAGE_SCHEMA_VERSION
from shared.storage.uploads import secure_media_upload_path


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
    builder_schema_version = models.PositiveSmallIntegerField(default=PAGE_SCHEMA_VERSION)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    published_at = models.DateTimeField(blank=True, null=True)
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="Schedule publish time")

    class Meta:
        ordering = ["-is_homepage", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "path"], name="cms_unique_site_path"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"

    @property
    def is_published(self) -> bool:
        return self.status == self.STATUS_PUBLISHED

    @property
    def is_scheduled(self) -> bool:
        return self.scheduled_at is not None


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
    builder_schema_version = models.PositiveSmallIntegerField(default=PAGE_SCHEMA_VERSION)
    builder_data = models.JSONField(default=dict, blank=True)
    html = models.TextField(blank=True)
    css = models.TextField(blank=True)
    js = models.TextField(blank=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["locale__code", "title"]
        constraints = [
            models.UniqueConstraint(fields=["page", "locale"], name="cms_unique_page_locale_translation"),
            models.UniqueConstraint(fields=["locale", "path"], name="cms_unique_locale_translation_path"),
        ]

    def __str__(self) -> str:
        return f"{self.page.title} [{self.locale.code}]"

    @property
    def is_published(self) -> bool:
        return self.status == self.STATUS_PUBLISHED


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
    file = models.FileField(upload_to=secure_media_upload_path)
    alt_text = models.CharField(max_length=255, blank=True)
    caption = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER)
    tags = models.JSONField(default=list, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    file_size = models.BigIntegerField(default=0)
    content_signature = models.CharField(max_length=128, blank=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="deleted_media_assets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


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


class AssetUsageReference(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="asset_usage_references", on_delete=models.CASCADE)
    asset = models.ForeignKey(MediaAsset, related_name="usage_references", on_delete=models.CASCADE)
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=120)
    field_name = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "entity_type", "entity_id", "field_name"],
                name="cms_unique_asset_usage_reference",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_id}: {self.entity_type}/{self.entity_id}"


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
    renderer_key = models.CharField(
        max_length=120,
        default="core.rich-text",
        help_text="Stable Next.js component registry key used to render this template.",
    )
    default_props_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Default props contract passed to the runtime component.",
    )
    version = models.PositiveSmallIntegerField(
        default=1,
        help_text="Template contract version for renderer compatibility checks.",
    )
    compatibility_flags = models.JSONField(
        default=dict,
        blank=True,
        help_text="Runtime compatibility toggles (for example, requires_blog, requires_commerce).",
    )
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
        return f"{self.site.name}: {self.source_path} -> {self.target_path}"


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


class SiteShell(TimeStampedModel):
    site = models.OneToOneField(Site, related_name="site_shell", on_delete=models.CASCADE)
    header_menu = models.ForeignKey(
        NavigationMenu,
        related_name="header_shells",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    footer_menu = models.ForeignKey(
        NavigationMenu,
        related_name="footer_shells",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    header_settings = models.JSONField(default=dict, blank=True)
    footer_settings = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Site shell"
        verbose_name_plural = "Site shells"

    def __str__(self) -> str:
        return f"{self.site.name}: shell"


class RobotsTxt(TimeStampedModel):
    site = models.OneToOneField(Site, related_name="robots_txt", on_delete=models.CASCADE)
    content = models.TextField(default="User-agent: *\nAllow: /")
    is_custom = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Robots.txt"
        verbose_name_plural = "Robots.txt"

    def __str__(self) -> str:
        return f"{self.site.name}: robots.txt"


class ReusableSection(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="reusable_sections", on_delete=models.CASCADE)
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="cms_unique_reusable_section_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class ThemeTemplate(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_MARKETPLACE = "marketplace"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_MARKETPLACE, "Marketplace"),
    ]

    site = models.ForeignKey(Site, related_name="theme_templates", on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True)
    is_global = models.BooleanField(default=False)
    tokens = models.JSONField(default=dict, blank=True)
    breakpoints = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-is_global", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="cms_unique_site_theme_template_slug"),
        ]

    def __str__(self) -> str:
        scope = "global" if self.is_global else str(self.site_id or "site")
        return f"{scope}: {self.slug}"


class PublishSnapshot(TimeStampedModel):
    TARGET_PAGE = "page"
    TARGET_POST = "post"
    TARGET_PRODUCT = "product"
    TARGET_SITE = "site"
    TARGET_CHOICES = [
        (TARGET_PAGE, "Page"),
        (TARGET_POST, "Post"),
        (TARGET_PRODUCT, "Product"),
        (TARGET_SITE, "Site"),
    ]

    site = models.ForeignKey(Site, related_name="publish_snapshots", on_delete=models.CASCADE)
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    target_id = models.PositiveIntegerField()
    revision_label = models.CharField(max_length=180, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="publish_snapshots",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "target_type", "target_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.target_type}/{self.target_id}"


class PreviewToken(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="preview_tokens", on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=128, unique=True)
    page = models.ForeignKey(Page, related_name="preview_tokens", on_delete=models.CASCADE, null=True, blank=True)
    locale = models.ForeignKey(SiteLocale, related_name="preview_tokens", on_delete=models.CASCADE, null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_preview_tokens",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "expires_at", "revoked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: preview token"
