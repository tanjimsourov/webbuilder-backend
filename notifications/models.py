"""Notifications app models."""

from django.db import models

from core.models import Site, TimeStampedModel


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


class WebhookDelivery(TimeStampedModel):
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
