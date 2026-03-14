from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformSubscription(models.Model):
    PLAN_STARTER = "starter"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CUSTOM = "custom"
    PLAN_CHOICES = [
        (PLAN_STARTER, "Starter"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
        (PLAN_CUSTOM, "Custom"),
    ]

    STATUS_TRIALING = "trialing"
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_PAUSED = "paused"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_TRIALING, "Trialing"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    BILLING_MONTHLY = "monthly"
    BILLING_YEARLY = "yearly"
    BILLING_CUSTOM = "custom"
    BILLING_CHOICES = [
        (BILLING_MONTHLY, "Monthly"),
        (BILLING_YEARLY, "Yearly"),
        (BILLING_CUSTOM, "Custom"),
    ]

    workspace = models.OneToOneField("Workspace", related_name="platform_subscription", on_delete=models.CASCADE)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_STARTER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIALING)
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CHOICES, default=BILLING_MONTHLY)
    seats = models.PositiveIntegerField(default=1)
    monthly_recurring_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    external_customer_id = models.CharField(max_length=120, blank=True)
    external_subscription_id = models.CharField(max_length=120, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_ends_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["workspace__name"]

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.plan} ({self.status})"


class PlatformOffer(models.Model):
    TYPE_PERCENTAGE = "percentage"
    TYPE_FIXED = "fixed"
    TYPE_TRIAL_EXTENSION = "trial_extension"
    TYPE_SEAT_BONUS = "seat_bonus"
    TYPE_CUSTOM = "custom"
    TYPE_CHOICES = [
        (TYPE_PERCENTAGE, "Percentage"),
        (TYPE_FIXED, "Fixed amount"),
        (TYPE_TRIAL_EXTENSION, "Trial extension"),
        (TYPE_SEAT_BONUS, "Seat bonus"),
        (TYPE_CUSTOM, "Custom"),
    ]

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

    TARGET_ALL = "all"
    TARGET_STARTER = "starter"
    TARGET_PRO = "pro"
    TARGET_ENTERPRISE = "enterprise"
    TARGET_CHOICES = [
        (TARGET_ALL, "All plans"),
        (TARGET_STARTER, "Starter"),
        (TARGET_PRO, "Pro"),
        (TARGET_ENTERPRISE, "Enterprise"),
    ]

    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=80, unique=True)
    headline = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    offer_type = models.CharField(max_length=24, choices=TYPE_CHOICES, default=TYPE_PERCENTAGE)
    target_plan = models.CharField(max_length=20, choices=TARGET_CHOICES, default=TARGET_ALL)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    duration_in_months = models.PositiveIntegerField(default=1)
    seats_delta = models.IntegerField(default=0)
    cta_url = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="created_platform_offers", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "name"]

    def __str__(self) -> str:
        return self.name


class PlatformEmailCampaign(models.Model):
    AUDIENCE_ALL_USERS = "all_users"
    AUDIENCE_WORKSPACE_OWNERS = "workspace_owners"
    AUDIENCE_ACTIVE_SUBSCRIBERS = "active_subscribers"
    AUDIENCE_TRIALING = "trialing"
    AUDIENCE_INACTIVE = "inactive_subscribers"
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL_USERS, "All users"),
        (AUDIENCE_WORKSPACE_OWNERS, "Workspace owners"),
        (AUDIENCE_ACTIVE_SUBSCRIBERS, "Active subscribers"),
        (AUDIENCE_TRIALING, "Trialing"),
        (AUDIENCE_INACTIVE, "Inactive subscribers"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SENDING = "sending"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    name = models.CharField(max_length=160)
    subject = models.CharField(max_length=220)
    preview_text = models.CharField(max_length=255, blank=True)
    body_text = models.TextField()
    body_html = models.TextField(blank=True)
    audience_type = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL_USERS)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    offer = models.ForeignKey("PlatformOffer", related_name="email_campaigns", on_delete=models.SET_NULL, null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="created_platform_email_campaigns", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self) -> str:
        return self.name
