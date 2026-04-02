from __future__ import annotations

from django.db import models

from core.models import Site, SiteLocale, TimeStampedModel


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
            models.UniqueConstraint(fields=["site", "path"], name="cms_unique_site_path"),
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
            models.UniqueConstraint(fields=["page", "locale"], name="cms_unique_page_locale_translation"),
            models.UniqueConstraint(fields=["locale", "path"], name="cms_unique_locale_translation_path"),
        ]

    def __str__(self) -> str:
        return f"{self.page.title} [{self.locale.code}]"
