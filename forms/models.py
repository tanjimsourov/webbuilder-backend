"""Forms app models."""

from __future__ import annotations

from django.db import models

from cms.models import Page
from core.models import Site, TimeStampedModel


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
        indexes = [
            models.Index(fields=["site", "form_name", "-created_at"]),
        ]

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
            models.UniqueConstraint(fields=["site", "slug"], name="forms_unique_site_form_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"
