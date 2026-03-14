from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Order, PlatformEmailCampaign, PlatformOffer, PlatformSubscription, Workspace


User = get_user_model()


class PlatformSubscriptionSerializer(serializers.ModelSerializer):
    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    owner_username = serializers.CharField(source="workspace.owner.username", read_only=True)
    owner_email = serializers.EmailField(source="workspace.owner.email", read_only=True)

    class Meta:
        model = PlatformSubscription
        fields = [
            "id",
            "workspace",
            "workspace_name",
            "owner_username",
            "owner_email",
            "plan",
            "status",
            "billing_cycle",
            "seats",
            "monthly_recurring_revenue",
            "external_customer_id",
            "external_subscription_id",
            "started_at",
            "trial_ends_at",
            "current_period_ends_at",
            "cancelled_at",
            "notes",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def validate_workspace(self, value: Workspace):
        instance = getattr(self, "instance", None)
        existing = PlatformSubscription.objects.filter(workspace=value)
        if instance is not None:
            existing = existing.exclude(pk=instance.pk)
        if existing.exists():
            raise serializers.ValidationError("This workspace already has a platform subscription.")
        return value


class PlatformOfferSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = PlatformOffer
        fields = [
            "id",
            "name",
            "code",
            "headline",
            "description",
            "offer_type",
            "target_plan",
            "discount_value",
            "duration_in_months",
            "seats_delta",
            "cta_url",
            "status",
            "starts_at",
            "ends_at",
            "metadata",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_by", "created_by_username", "created_at", "updated_at"]


class PlatformEmailCampaignSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    offer_name = serializers.CharField(source="offer.name", read_only=True)

    class Meta:
        model = PlatformEmailCampaign
        fields = [
            "id",
            "name",
            "subject",
            "preview_text",
            "body_text",
            "body_html",
            "audience_type",
            "status",
            "offer",
            "offer_name",
            "recipient_count",
            "sent_count",
            "last_error",
            "sent_at",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "recipient_count",
            "sent_count",
            "last_error",
            "sent_at",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]


class PlatformAdminUserSerializer(serializers.ModelSerializer):
    workspace_count = serializers.IntegerField(read_only=True)
    site_count = serializers.IntegerField(read_only=True)
    order_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "is_superuser",
            "is_active",
            "date_joined",
            "last_login",
            "workspace_count",
            "site_count",
            "order_count",
        ]


class PlatformAdminWorkspaceSerializer(serializers.ModelSerializer):
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    site_count = serializers.IntegerField(read_only=True)
    subscription = PlatformSubscriptionSerializer(source="platform_subscription", read_only=True)

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "owner",
            "owner_username",
            "owner_email",
            "is_personal",
            "member_count",
            "site_count",
            "settings",
            "subscription",
            "created_at",
            "updated_at",
        ]


class PlatformAdminRecentOrderSerializer(serializers.ModelSerializer):
    site_name = serializers.CharField(source="site.name", read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "site",
            "site_name",
            "customer_name",
            "customer_email",
            "status",
            "payment_status",
            "currency",
            "total",
            "placed_at",
        ]
