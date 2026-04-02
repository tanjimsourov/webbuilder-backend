"""Payment and subscription models."""

from __future__ import annotations

from django.db import models

from core.models import Site, TimeStampedModel, Workspace


class SubscriptionPlan(TimeStampedModel):
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    interval = models.CharField(max_length=20, default="month")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["price"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} {self.currency}/{self.interval})"


class Subscription(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, related_name="subscriptions", on_delete=models.CASCADE)
    plan = models.ForeignKey(SubscriptionPlan, related_name="subscriptions", on_delete=models.PROTECT)
    status = models.CharField(max_length=30, default="active")
    current_period_end = models.DateTimeField()
    stripe_subscription_id = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.plan.name} ({self.status})"


class PaymentTransaction(TimeStampedModel):
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
    transaction = models.ForeignKey(PaymentTransaction, related_name="invoices", on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField()
    pdf_file = models.FileField(upload_to="invoices/", blank=True)

    def __str__(self) -> str:
        return self.invoice_number
