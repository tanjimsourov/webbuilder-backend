from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order, PlatformEmailCampaign, PlatformOffer, PlatformSubscription, Site, Workspace
from .platform_admin_serializers import (
    PlatformAdminRecentOrderSerializer,
    PlatformAdminUserSerializer,
    PlatformAdminWorkspaceSerializer,
    PlatformEmailCampaignSerializer,
    PlatformOfferSerializer,
    PlatformSubscriptionSerializer,
)
from .platform_admin_services import send_platform_campaign


User = get_user_model()


class IsPlatformOwner(permissions.BasePermission):
    message = "Only the platform owner can access this area."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def _annotated_user_queryset():
    return User.objects.annotate(
        workspace_count=Count("workspace_memberships__workspace", distinct=True),
        site_count=Count("workspace_memberships__workspace__sites", distinct=True),
        order_count=Count("workspace_memberships__workspace__sites__orders", distinct=True),
    )


def _annotated_workspace_queryset():
    return Workspace.objects.select_related("owner", "platform_subscription").annotate(
        member_count=Count("memberships", distinct=True),
        site_count=Count("sites", distinct=True),
    )


class PlatformAdminOverviewView(APIView):
    permission_classes = [IsPlatformOwner]

    def get(self, request):
        recent_cutoff = timezone.now() - timedelta(days=30)
        paid_order_filter = Q(payment_status=Order.PAYMENT_PAID)
        active_subscription_filter = Q(status=PlatformSubscription.STATUS_ACTIVE)
        trialing_subscription_filter = Q(status=PlatformSubscription.STATUS_TRIALING)
        past_due_subscription_filter = Q(status=PlatformSubscription.STATUS_PAST_DUE)

        total_revenue = Order.objects.filter(paid_order_filter).aggregate(total=Sum("total"))["total"] or Decimal("0.00")
        mrr = PlatformSubscription.objects.filter(active_subscription_filter).aggregate(
            total=Sum("monthly_recurring_revenue")
        )["total"] or Decimal("0.00")

        recent_users = _annotated_user_queryset().order_by("-date_joined")[:5]
        recent_workspaces = _annotated_workspace_queryset().order_by("-created_at")[:5]
        recent_orders = Order.objects.select_related("site").order_by("-placed_at")[:5]

        payload = {
            "metrics": {
                "total_users": User.objects.count(),
                "active_users_30d": User.objects.filter(last_login__gte=recent_cutoff).count(),
                "total_workspaces": Workspace.objects.count(),
                "total_sites": Site.objects.count(),
                "total_orders": Order.objects.count(),
                "paid_orders": Order.objects.filter(paid_order_filter).count(),
                "total_revenue": f"{total_revenue:.2f}",
                "subscriptions_active": PlatformSubscription.objects.filter(active_subscription_filter).count(),
                "subscriptions_trialing": PlatformSubscription.objects.filter(trialing_subscription_filter).count(),
                "subscriptions_past_due": PlatformSubscription.objects.filter(past_due_subscription_filter).count(),
                "mrr": f"{mrr:.2f}",
                "active_offers": PlatformOffer.objects.filter(status=PlatformOffer.STATUS_ACTIVE).count(),
                "sent_campaigns": PlatformEmailCampaign.objects.filter(status=PlatformEmailCampaign.STATUS_SENT).count(),
            },
            "recent_users": PlatformAdminUserSerializer(recent_users, many=True).data,
            "recent_workspaces": PlatformAdminWorkspaceSerializer(recent_workspaces, many=True).data,
            "recent_orders": PlatformAdminRecentOrderSerializer(recent_orders, many=True).data,
        }
        return Response(payload)


class PlatformAdminUsersView(APIView):
    permission_classes = [IsPlatformOwner]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        users = _annotated_user_queryset().order_by("-date_joined")
        if query:
            users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
        return Response(PlatformAdminUserSerializer(users, many=True).data)


class PlatformAdminWorkspacesView(APIView):
    permission_classes = [IsPlatformOwner]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        workspaces = _annotated_workspace_queryset().order_by("-created_at")
        if query:
            workspaces = workspaces.filter(
                Q(name__icontains=query)
                | Q(slug__icontains=query)
                | Q(owner__username__icontains=query)
                | Q(owner__email__icontains=query)
            )
        return Response(PlatformAdminWorkspaceSerializer(workspaces, many=True).data)


class PlatformSubscriptionViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformSubscriptionSerializer
    permission_classes = [IsPlatformOwner]
    queryset = PlatformSubscription.objects.select_related("workspace", "workspace__owner").order_by("-updated_at")

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        subscription = self.get_object()
        subscription.status = PlatformSubscription.STATUS_PAUSED
        subscription.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(subscription).data)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        subscription = self.get_object()
        subscription.status = PlatformSubscription.STATUS_ACTIVE
        subscription.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(subscription).data)


class PlatformOfferViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformOfferSerializer
    permission_classes = [IsPlatformOwner]
    queryset = PlatformOffer.objects.select_related("created_by").order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PlatformEmailCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformEmailCampaignSerializer
    permission_classes = [IsPlatformOwner]
    queryset = PlatformEmailCampaign.objects.select_related("created_by", "offer").order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def send_now(self, request, pk=None):
        campaign = self.get_object()
        campaign = send_platform_campaign(campaign)
        serializer = self.get_serializer(campaign)
        return Response(serializer.data)


class PlatformAdminUserStatusView(APIView):
    permission_classes = [IsPlatformOwner]

    def post(self, request, user_id: int, action: str):
        user = User.objects.filter(pk=user_id).first()
        if not user:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if action == "activate":
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=["is_active", "last_login"])  # last_login update harmless
            return Response({"id": user.id, "is_active": user.is_active})
        elif action == "deactivate":
            if user.is_active:
                user.is_active = False
                user.save(update_fields=["is_active"]) 
            return Response({"id": user.id, "is_active": user.is_active})
        else:
            return Response({"detail": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)
