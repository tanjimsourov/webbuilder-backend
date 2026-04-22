"""Payment and subscription models.

This module stores plans, subscriptions, transactions, and invoices.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from core.models import Site, TimeStampedModel, Workspace


class SubscriptionPlan(TimeStampedModel):
    """A billable plan configured in the platform."""

    PLAN_FREE = "free"
    PLAN_PRO = "pro"
    PLAN_ENTERPRISE = "enterprise"
    PLAN_CHOICES = [
        (PLAN_FREE, "Free"),
        (PLAN_PRO, "Pro"),
        (PLAN_ENTERPRISE, "Enterprise"),
    ]

    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    stripe_price_id = models.CharField(max_length=120, blank=True)
    amount = models.IntegerField(default=0, help_text="Amount in cents.")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="usd")
    interval = models.CharField(max_length=20, default="month")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["amount", "price"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} {self.currency}/{self.interval})"


class Subscription(TimeStampedModel):
    """Subscription purchased by a user/workspace."""

    customer = models.ForeignKey(
        get_user_model(),
        related_name="subscriptions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name="subscriptions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    plan = models.ForeignKey(SubscriptionPlan, related_name="subscriptions", on_delete=models.PROTECT)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=30, default="active")
    current_period_end = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        owner = self.customer or self.workspace or "Unknown"
        return f"{owner}: {self.plan.name} ({self.status})"


# Alias kept for naming parity with migration docs.
CustomerSubscription = Subscription


class PaymentTransaction(TimeStampedModel):
    """One-time or recurring transaction records."""

    subscription = models.ForeignKey(
        Subscription,
        related_name="transactions",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="payment_transactions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=30, default="pending")
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency} ({self.status})"


class Invoice(TimeStampedModel):
    """Invoice record tied to a subscription and optional transaction."""

    subscription = models.ForeignKey(
        Subscription,
        related_name="invoices",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    transaction = models.ForeignKey(
        PaymentTransaction,
        related_name="invoices",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    invoice_number = models.CharField(max_length=64, unique=True, blank=True)
    stripe_invoice_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    amount_due = models.IntegerField(default=0)
    currency = models.CharField(max_length=10, default="usd")
    paid = models.BooleanField(default=False)
    issued_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    pdf_file = models.FileField(upload_to="invoices/", blank=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return self.stripe_invoice_id or self.invoice_number or f"Invoice {self.pk}"


class PlanEntitlement(TimeStampedModel):
    plan = models.ForeignKey(SubscriptionPlan, related_name="entitlements", on_delete=models.CASCADE)
    code = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True)
    is_unlimited = models.BooleanField(default=False)
    limit_value = models.BigIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["plan__slug", "code"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "code"], name="payments_unique_plan_entitlement"),
        ]

    def __str__(self) -> str:
        suffix = "unlimited" if self.is_unlimited else str(self.limit_value)
        return f"{self.plan.slug}:{self.code}={suffix}"


class WorkspaceSubscription(TimeStampedModel):
    STATUS_TRIALING = "trialing"
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_TRIALING, "Trialing"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAST_DUE, "Past due"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    workspace = models.OneToOneField(Workspace, related_name="active_subscription", on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, related_name="workspace_subscriptions", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TRIALING)
    starts_at = models.DateTimeField(default=timezone.now)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    external_reference = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.workspace.slug}:{self.plan.slug}:{self.status}"


class WorkspaceUsageRecord(TimeStampedModel):
    METRIC_SITES = "sites"
    METRIC_USERS = "users"
    METRIC_AI_REQUESTS = "ai_requests"
    METRIC_AI_TOKENS = "ai_tokens"
    METRIC_ANALYTICS_EVENTS = "analytics_events"
    METRIC_STORAGE_BYTES = "storage_bytes"
    METRIC_CHOICES = [
        (METRIC_SITES, "Sites"),
        (METRIC_USERS, "Users"),
        (METRIC_AI_REQUESTS, "AI requests"),
        (METRIC_AI_TOKENS, "AI tokens"),
        (METRIC_ANALYTICS_EVENTS, "Analytics events"),
        (METRIC_STORAGE_BYTES, "Storage bytes"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="usage_records", on_delete=models.CASCADE)
    metric = models.CharField(max_length=40, choices=METRIC_CHOICES)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    used_value = models.BigIntegerField(default=0)
    limit_value = models.BigIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-period_start", "workspace__slug", "metric"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "metric", "period_start", "period_end"],
                name="payments_unique_workspace_usage_period",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "metric", "period_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.workspace.slug}:{self.metric}:{self.used_value}"
