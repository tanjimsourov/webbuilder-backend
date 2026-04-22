"""Notifications app models."""

from django.contrib.auth import get_user_model
from django.db import models

from core.models import Site, TimeStampedModel, Workspace


class Webhook(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    EVENT_PAGE_PUBLISHED = "page.published"
    EVENT_SITE_PUBLISHED = "site.published"
    EVENT_POST_PUBLISHED = "post.published"
    EVENT_PRODUCT_PUBLISHED = "product.published"
    EVENT_ORDER_CREATED = "order.created"
    EVENT_CUSTOMER_CREATED = "customer.created"
    EVENT_FORM_SUBMITTED = "form.submitted"
    EVENT_AI_JOB_COMPLETED = "ai.job.completed"
    EVENT_AI_JOB_FAILED = "ai.job.failed"
    EVENT_PUBLISH_JOB_COMPLETED = "publish.job.completed"
    EVENT_CHOICES = [
        (EVENT_PAGE_PUBLISHED, "Page Published"),
        (EVENT_SITE_PUBLISHED, "Site Published"),
        (EVENT_POST_PUBLISHED, "Post Published"),
        (EVENT_PRODUCT_PUBLISHED, "Product Published"),
        (EVENT_ORDER_CREATED, "Order Created"),
        (EVENT_CUSTOMER_CREATED, "Customer Created"),
        (EVENT_FORM_SUBMITTED, "Form Submitted"),
        (EVENT_AI_JOB_COMPLETED, "AI Job Completed"),
        (EVENT_AI_JOB_FAILED, "AI Job Failed"),
        (EVENT_PUBLISH_JOB_COMPLETED, "Publish Job Completed"),
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


class AutomationWebhook(TimeStampedModel):
    EVENT_SITE_PUBLISHED = "site.published"
    EVENT_POST_PUBLISHED = "post.published"
    EVENT_ORDER_CREATED = "order.created"
    EVENT_CUSTOMER_CREATED = "customer.created"
    EVENT_FORM_SUBMITTED = "form.submitted"
    EVENT_AI_JOB_COMPLETED = "ai.job.completed"
    EVENT_PUBLISH_JOB_COMPLETED = "publish.job.completed"
    EVENT_CHOICES = [
        (EVENT_SITE_PUBLISHED, "Site Published"),
        (EVENT_POST_PUBLISHED, "Post Published"),
        (EVENT_ORDER_CREATED, "Order Created"),
        (EVENT_CUSTOMER_CREATED, "Customer Created"),
        (EVENT_FORM_SUBMITTED, "Form Submitted"),
        (EVENT_AI_JOB_COMPLETED, "AI Job Completed"),
        (EVENT_PUBLISH_JOB_COMPLETED, "Publish Job Completed"),
    ]

    site = models.ForeignKey(Site, related_name="automation_webhooks", on_delete=models.CASCADE)
    name = models.CharField(max_length=140)
    url = models.URLField(max_length=500)
    event = models.CharField(max_length=80, choices=EVENT_CHOICES)
    is_active = models.BooleanField(default=True)
    secret = models.CharField(max_length=120, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=15)
    max_attempts = models.PositiveIntegerField(default=5)

    class Meta:
        db_table = "automation_webhooks"
        ordering = ["event", "name"]
        constraints = [
            models.UniqueConstraint(fields=["site", "name", "event"], name="notifications_unique_automation_webhook"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name} ({self.event})"


class AutomationWebhookDelivery(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]

    webhook = models.ForeignKey(
        AutomationWebhook,
        related_name="deliveries",
        on_delete=models.CASCADE,
    )
    event = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
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


class WebhookEndpoint(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_DISABLED = "disabled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_DISABLED, "Disabled"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        related_name="webhook_endpoints",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="integration_webhook_endpoints",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=160)
    url = models.URLField(max_length=500)
    subscribed_events = models.JSONField(default=list, blank=True)
    signing_secret = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    max_attempts = models.PositiveIntegerField(default=5)
    timeout_seconds = models.PositiveIntegerField(default=15)
    headers = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "webhook_endpoints"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return self.name


class WebhookEndpointDelivery(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]

    endpoint = models.ForeignKey(
        WebhookEndpoint,
        related_name="deliveries",
        on_delete=models.CASCADE,
    )
    event = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "webhook_deliveries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["endpoint", "event", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.endpoint_id}:{self.event}:{self.status}"


class Notification(TimeStampedModel):
    CHANNEL_EMAIL = "email"
    CHANNEL_IN_APP = "in_app"
    CHANNEL_WEBHOOK = "webhook"
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, "Email"),
        (CHANNEL_IN_APP, "In-app"),
        (CHANNEL_WEBHOOK, "Webhook"),
    ]

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_READ = "read"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_READ, "Read"),
    ]

    recipient = models.ForeignKey(
        get_user_model(),
        related_name="notifications",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name="notifications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="notifications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "status", "created_at"]),
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.status}"
