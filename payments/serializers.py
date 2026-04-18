"""Serializers for payment and subscription models."""

from __future__ import annotations

from rest_framework import serializers

from payments.models import Invoice, Subscription, SubscriptionPlan


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "slug",
            "stripe_price_id",
            "amount",
            "price",
            "currency",
            "interval",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]


class CustomerSubscriptionSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(
        source="plan",
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        write_only=True,
    )

    class Meta:
        model = Subscription
        fields = [
            "id",
            "customer",
            "workspace",
            "plan",
            "plan_id",
            "stripe_subscription_id",
            "status",
            "current_period_end",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "customer",
            "workspace",
            "stripe_subscription_id",
            "status",
            "current_period_end",
            "created_at",
            "updated_at",
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = [
            "id",
            "subscription",
            "transaction",
            "invoice_number",
            "stripe_invoice_id",
            "amount_due",
            "currency",
            "paid",
            "issued_at",
            "due_at",
            "paid_at",
            "pdf_file",
            "created_at",
            "updated_at",
        ]
