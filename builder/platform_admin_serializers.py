from django.contrib.auth import get_user_model
from rest_framework import serializers

from core.models import SecurityAuditLog, SiteMembership, UserAccount
from .models import Order, PlatformEmailCampaign, PlatformOffer, PlatformSubscription, Workspace, WorkspaceMembership


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
    account_status = serializers.CharField(source="account.status", read_only=True)
    support_agent = serializers.BooleanField(source="account.is_support_agent", read_only=True)
    mfa_enabled = serializers.BooleanField(source="account.mfa_enabled", read_only=True)
    email_verified = serializers.SerializerMethodField()

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
            "account_status",
            "support_agent",
            "mfa_enabled",
            "email_verified",
            "workspace_count",
            "site_count",
            "order_count",
        ]

    def get_email_verified(self, obj) -> bool:
        account = getattr(obj, "account", None)
        return bool(account and account.email_verified_at)


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


class PlatformAdminUserRoleUpdateSerializer(serializers.Serializer):
    is_superuser = serializers.BooleanField(required=False)
    is_staff = serializers.BooleanField(required=False)
    is_support_agent = serializers.BooleanField(required=False)
    account_status = serializers.ChoiceField(choices=UserAccount.STATUS_CHOICES, required=False)


class PlatformAdminWorkspaceMembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = [
            "id",
            "workspace",
            "user",
            "username",
            "email",
            "role",
            "status",
            "invited_by",
            "accepted_at",
            "created_at",
            "updated_at",
        ]


class PlatformAdminWorkspaceMembershipUpsertSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    role = serializers.ChoiceField(choices=WorkspaceMembership.ROLE_CHOICES)
    status = serializers.ChoiceField(choices=WorkspaceMembership.STATUS_CHOICES, required=False)


class PlatformAdminSiteMembershipSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = SiteMembership
        fields = [
            "id",
            "site",
            "user",
            "username",
            "email",
            "role",
            "status",
            "granted_by",
            "accepted_at",
            "created_at",
            "updated_at",
        ]


class PlatformAdminSiteMembershipUpsertSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    role = serializers.ChoiceField(choices=SiteMembership.ROLE_CHOICES)
    status = serializers.ChoiceField(choices=SiteMembership.STATUS_CHOICES, required=False)


class PlatformAdminImpersonationSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=280, required=False, allow_blank=True)


class PlatformAdminSecurityTimelineSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = SecurityAuditLog
        fields = [
            "id",
            "created_at",
            "action",
            "actor",
            "actor_username",
            "target_type",
            "target_id",
            "request_id",
            "ip_address",
            "success",
            "metadata",
        ]
