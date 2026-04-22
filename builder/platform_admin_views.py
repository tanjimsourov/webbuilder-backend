from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    ImpersonationAudit,
    SecurityAuditLog,
    SiteMembership,
    UserAccount,
    UserSecurityState,
    UserSession,
    WorkspaceMembership,
)
from .models import Order, PlatformEmailCampaign, PlatformOffer, PlatformSubscription, Site, Workspace
from .platform_admin_serializers import (
    PlatformAdminImpersonationSerializer,
    PlatformAdminRecentOrderSerializer,
    PlatformAdminSecurityTimelineSerializer,
    PlatformAdminSiteMembershipSerializer,
    PlatformAdminSiteMembershipUpsertSerializer,
    PlatformAdminUserRoleUpdateSerializer,
    PlatformAdminUserSerializer,
    PlatformAdminWorkspaceMembershipSerializer,
    PlatformAdminWorkspaceMembershipUpsertSerializer,
    PlatformAdminWorkspaceSerializer,
    PlatformEmailCampaignSerializer,
    PlatformOfferSerializer,
    PlatformSubscriptionSerializer,
)
from .platform_admin_services import send_platform_campaign
from .throttles import AdminAPIThrottle
from shared.auth.audit import log_security_event
from shared.auth.sessions import start_user_session
from shared.policies.access import can_impersonate


User = get_user_model()


class IsPlatformOwner(permissions.BasePermission):
    message = "Only the platform owner can access this area."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsPlatformOperator(permissions.BasePermission):
    message = "Only platform operators can access this endpoint."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        account = getattr(request.user, "account", None)
        return bool(account and account.is_support_agent and account.status == UserAccount.STATUS_ACTIVE)


def _annotated_user_queryset():
    return User.objects.select_related("account").annotate(
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
    throttle_classes = [AdminAPIThrottle]

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
    throttle_classes = [AdminAPIThrottle]

    def get(self, request):
        query = (request.query_params.get("q") or "").strip()
        users = _annotated_user_queryset().order_by("-date_joined")
        if query:
            users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
        return Response(PlatformAdminUserSerializer(users, many=True).data)


class PlatformAdminWorkspacesView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

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
    throttle_classes = [AdminAPIThrottle]
    queryset = PlatformSubscription.objects.select_related("workspace", "workspace__owner").order_by("-updated_at")

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        subscription = self.get_object()
        subscription.status = PlatformSubscription.STATUS_PAUSED
        subscription.save(update_fields=["status", "updated_at"])
        log_security_event(
            "platform.subscription.pause",
            request=request,
            actor=request.user,
            target_type="platform_subscription",
            target_id=str(subscription.pk),
        )
        return Response(self.get_serializer(subscription).data)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        subscription = self.get_object()
        subscription.status = PlatformSubscription.STATUS_ACTIVE
        subscription.save(update_fields=["status", "updated_at"])
        log_security_event(
            "platform.subscription.resume",
            request=request,
            actor=request.user,
            target_type="platform_subscription",
            target_id=str(subscription.pk),
        )
        return Response(self.get_serializer(subscription).data)


class PlatformOfferViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformOfferSerializer
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]
    queryset = PlatformOffer.objects.select_related("created_by").order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class PlatformEmailCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformEmailCampaignSerializer
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]
    queryset = PlatformEmailCampaign.objects.select_related("created_by", "offer").order_by("-updated_at")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def send_now(self, request, pk=None):
        campaign = self.get_object()
        campaign = send_platform_campaign(campaign)
        log_security_event(
            "platform.campaign.send",
            request=request,
            actor=request.user,
            target_type="platform_email_campaign",
            target_id=str(campaign.pk),
        )
        serializer = self.get_serializer(campaign)
        return Response(serializer.data)


class PlatformAdminUserStatusView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

    def post(self, request, user_id: int, action: str):
        user = User.objects.filter(pk=user_id).first()
        if not user:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        account, _ = UserAccount.objects.get_or_create(
            user=user,
            defaults={"email": (user.email or f"user-{user.pk}@local.invalid").strip().lower()},
        )
        security_state, _ = UserSecurityState.objects.get_or_create(user=user)

        if action == "activate":
            if not user.is_active:
                user.is_active = True
                user.save(update_fields=["is_active", "last_login"])  # last_login update harmless
            if account.status != UserAccount.STATUS_ACTIVE:
                account.status = UserAccount.STATUS_ACTIVE
                account.save(update_fields=["status", "updated_at"])
                log_security_event(
                    "platform.user.activate",
                    request=request,
                    actor=request.user,
                    target_type="user",
                    target_id=str(user.pk),
                )
            return Response({"id": user.id, "is_active": user.is_active})
        elif action == "deactivate":
            if user.is_active:
                user.is_active = False
                user.save(update_fields=["is_active"])
            if account.status != UserAccount.STATUS_SUSPENDED:
                account.status = UserAccount.STATUS_SUSPENDED
                account.save(update_fields=["status", "updated_at"])
                log_security_event(
                    "platform.user.deactivate",
                    request=request,
                    actor=request.user,
                    target_type="user",
                    target_id=str(user.pk),
                )
            return Response({"id": user.id, "is_active": user.is_active})
        elif action == "lock":
            account.status = UserAccount.STATUS_LOCKED
            account.save(update_fields=["status", "updated_at"])
            security_state.locked_until = timezone.now() + timedelta(
                seconds=max(60, int(getattr(settings, "AUTH_LOCKOUT_SECONDS", 900) or 900))
            )
            security_state.failed_login_count = max(1, int(security_state.failed_login_count or 0))
            security_state.save(update_fields=["locked_until", "failed_login_count", "updated_at"])
            log_security_event(
                "platform.user.lock",
                request=request,
                actor=request.user,
                target_type="user",
                target_id=str(user.pk),
            )
            return Response({"id": user.id, "status": account.status})
        elif action == "unlock":
            account.status = UserAccount.STATUS_ACTIVE
            account.save(update_fields=["status", "updated_at"])
            security_state.locked_until = None
            security_state.failed_login_count = 0
            security_state.save(update_fields=["locked_until", "failed_login_count", "updated_at"])
            log_security_event(
                "platform.user.unlock",
                request=request,
                actor=request.user,
                target_type="user",
                target_id=str(user.pk),
            )
            return Response({"id": user.id, "status": account.status})
        else:
            return Response({"detail": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)


class PlatformAdminUserRoleAssignmentView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

    def post(self, request, user_id: int):
        user = User.objects.filter(pk=user_id).first()
        if not user:
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        serializer = PlatformAdminUserRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        updates: list[str] = []
        if "is_superuser" in payload and user.is_superuser != payload["is_superuser"]:
            user.is_superuser = payload["is_superuser"]
            updates.append("is_superuser")
        if "is_staff" in payload and user.is_staff != payload["is_staff"]:
            user.is_staff = payload["is_staff"]
            updates.append("is_staff")
        if updates:
            user.save(update_fields=updates)

        account, _ = UserAccount.objects.get_or_create(
            user=user,
            defaults={"email": (user.email or f"user-{user.pk}@local.invalid").strip().lower()},
        )
        account_updates: list[str] = []
        if "is_support_agent" in payload and account.is_support_agent != payload["is_support_agent"]:
            account.is_support_agent = payload["is_support_agent"]
            account_updates.append("is_support_agent")
        if "account_status" in payload and account.status != payload["account_status"]:
            account.status = payload["account_status"]
            account_updates.append("status")
        if account_updates:
            account.save(update_fields=[*account_updates, "updated_at"])

        log_security_event(
            "platform.user.roles.update",
            request=request,
            actor=request.user,
            target_type="user",
            target_id=str(user.pk),
            metadata={
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "is_support_agent": account.is_support_agent,
                "account_status": account.status,
            },
        )
        refreshed = _annotated_user_queryset().get(pk=user.pk)
        return Response(PlatformAdminUserSerializer(refreshed).data)


class PlatformAdminWorkspaceMembershipView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

    def get(self, request, workspace_id: int):
        workspace = get_object_or_404(Workspace, pk=workspace_id)
        memberships = workspace.memberships.select_related("user", "invited_by").order_by("role", "user__username")
        return Response(PlatformAdminWorkspaceMembershipSerializer(memberships, many=True).data)

    def post(self, request, workspace_id: int):
        workspace = get_object_or_404(Workspace, pk=workspace_id)
        serializer = PlatformAdminWorkspaceMembershipUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        member_user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        membership, created = WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=member_user,
            defaults={
                "role": serializer.validated_data["role"],
                "status": serializer.validated_data.get("status", WorkspaceMembership.STATUS_ACTIVE),
                "invited_by": request.user,
                "accepted_at": timezone.now(),
            },
        )
        if not created:
            membership.role = serializer.validated_data["role"]
            membership.status = serializer.validated_data.get("status", membership.status)
            if membership.accepted_at is None:
                membership.accepted_at = timezone.now()
            membership.save(update_fields=["role", "status", "accepted_at", "updated_at"])

        log_security_event(
            "platform.workspace.membership.upsert",
            request=request,
            actor=request.user,
            target_type="workspace_membership",
            target_id=str(membership.pk),
            metadata={"workspace_id": workspace.pk, "created": created},
        )
        return Response(
            PlatformAdminWorkspaceMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def patch(self, request, workspace_id: int, membership_id: int):
        workspace = get_object_or_404(Workspace, pk=workspace_id)
        membership = get_object_or_404(WorkspaceMembership, pk=membership_id, workspace=workspace)
        serializer = PlatformAdminWorkspaceMembershipUpsertSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        updates: list[str] = []
        if "role" in payload:
            membership.role = payload["role"]
            updates.append("role")
        if "status" in payload:
            membership.status = payload["status"]
            updates.append("status")
        if updates:
            membership.save(update_fields=[*updates, "updated_at"])
        log_security_event(
            "platform.workspace.membership.update",
            request=request,
            actor=request.user,
            target_type="workspace_membership",
            target_id=str(membership.pk),
            metadata={"workspace_id": workspace.pk},
        )
        return Response(PlatformAdminWorkspaceMembershipSerializer(membership).data)

    def delete(self, request, workspace_id: int, membership_id: int):
        workspace = get_object_or_404(Workspace, pk=workspace_id)
        membership = get_object_or_404(WorkspaceMembership, pk=membership_id, workspace=workspace)
        if membership.role == WorkspaceMembership.ROLE_OWNER:
            return Response({"detail": "Cannot remove workspace owner membership."}, status=status.HTTP_400_BAD_REQUEST)
        membership.delete()
        log_security_event(
            "platform.workspace.membership.delete",
            request=request,
            actor=request.user,
            target_type="workspace_membership",
            target_id=str(membership_id),
            metadata={"workspace_id": workspace.pk},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformAdminSiteMembershipView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

    def get(self, request, site_id: int):
        site = get_object_or_404(Site, pk=site_id)
        memberships = site.memberships.select_related("user", "granted_by").order_by("role", "user__username")
        return Response(PlatformAdminSiteMembershipSerializer(memberships, many=True).data)

    def post(self, request, site_id: int):
        site = get_object_or_404(Site, pk=site_id)
        serializer = PlatformAdminSiteMembershipUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member_user = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        membership, created = SiteMembership.objects.get_or_create(
            site=site,
            user=member_user,
            defaults={
                "role": serializer.validated_data["role"],
                "status": serializer.validated_data.get("status", SiteMembership.STATUS_ACTIVE),
                "granted_by": request.user,
                "accepted_at": timezone.now(),
            },
        )
        if not created:
            membership.role = serializer.validated_data["role"]
            membership.status = serializer.validated_data.get("status", membership.status)
            membership.granted_by = request.user
            if membership.accepted_at is None:
                membership.accepted_at = timezone.now()
            membership.save(update_fields=["role", "status", "granted_by", "accepted_at", "updated_at"])

        log_security_event(
            "platform.site.membership.upsert",
            request=request,
            actor=request.user,
            target_type="site_membership",
            target_id=str(membership.pk),
            metadata={"site_id": site.pk, "created": created},
        )
        return Response(
            PlatformAdminSiteMembershipSerializer(membership).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def patch(self, request, site_id: int, membership_id: int):
        site = get_object_or_404(Site, pk=site_id)
        membership = get_object_or_404(SiteMembership, pk=membership_id, site=site)
        serializer = PlatformAdminSiteMembershipUpsertSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        updates: list[str] = []
        if "role" in payload:
            membership.role = payload["role"]
            updates.append("role")
        if "status" in payload:
            membership.status = payload["status"]
            updates.append("status")
        if updates:
            membership.save(update_fields=[*updates, "updated_at"])

        log_security_event(
            "platform.site.membership.update",
            request=request,
            actor=request.user,
            target_type="site_membership",
            target_id=str(membership.pk),
            metadata={"site_id": site.pk},
        )
        return Response(PlatformAdminSiteMembershipSerializer(membership).data)

    def delete(self, request, site_id: int, membership_id: int):
        site = get_object_or_404(Site, pk=site_id)
        membership = get_object_or_404(SiteMembership, pk=membership_id, site=site)
        if membership.role == SiteMembership.ROLE_SITE_OWNER:
            return Response({"detail": "Cannot remove site owner membership."}, status=status.HTTP_400_BAD_REQUEST)
        membership.delete()
        log_security_event(
            "platform.site.membership.delete",
            request=request,
            actor=request.user,
            target_type="site_membership",
            target_id=str(membership_id),
            metadata={"site_id": site.pk},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformAdminUserSecurityTimelineView(APIView):
    permission_classes = [IsPlatformOwner]
    throttle_classes = [AdminAPIThrottle]

    def get(self, request, user_id: int):
        user = get_object_or_404(User, pk=user_id)
        limit = min(max(int(request.query_params.get("limit", 200)), 1), 1000)
        events = (
            SecurityAuditLog.objects.filter(
                Q(actor=user) | Q(target_type="user", target_id=str(user.pk))
            )
            .order_by("-created_at")[:limit]
        )
        return Response({"results": PlatformAdminSecurityTimelineSerializer(events, many=True).data})


class PlatformImpersonationStartView(APIView):
    permission_classes = [IsPlatformOperator]
    throttle_classes = [AdminAPIThrottle]

    def post(self, request):
        serializer = PlatformAdminImpersonationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = get_object_or_404(User, pk=serializer.validated_data["user_id"])
        actor_user = request.user
        if target.is_superuser and not request.user.is_superuser:
            return Response({"detail": "Support cannot impersonate super admins."}, status=status.HTTP_403_FORBIDDEN)
        if not can_impersonate(request.user):
            return Response({"detail": "Not authorized to impersonate users."}, status=status.HTTP_403_FORBIDDEN)
        if request.user.id == target.id:
            return Response({"detail": "Cannot impersonate your own account."}, status=status.HTTP_400_BAD_REQUEST)

        if not request.session.get("impersonator_user_id"):
            request.session["impersonator_user_id"] = request.user.id
        login(request, target)
        audit = ImpersonationAudit.objects.create(
            actor_id=request.session.get("impersonator_user_id"),
            target=target,
            reason=serializer.validated_data.get("reason", ""),
            session_key=request.session.session_key or "",
            request_id=getattr(request, "request_id", "")[:128],
            ip_address=(request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[
                0
            ].strip()
            or None,
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:500],
        )
        request.session["active_impersonation_audit_id"] = audit.id
        request.session["active_user_session_id"] = None
        start_user_session(request=request, user=target, auth_method=UserSession.AUTH_IMPERSONATION, impersonated_by=actor_user)
        log_security_event(
            "platform.impersonation.start",
            request=request,
            actor=actor_user,
            target_type="user",
            target_id=str(target.pk),
            metadata={"reason": serializer.validated_data.get("reason", "")},
        )
        return Response({"impersonating": True, "user_id": target.id, "username": target.username})


class PlatformImpersonationStopView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AdminAPIThrottle]

    def post(self, request):
        impersonator_user_id = request.session.get("impersonator_user_id")
        if not impersonator_user_id:
            return Response({"detail": "No active impersonation session."}, status=status.HTTP_400_BAD_REQUEST)
        impersonator = get_object_or_404(User, pk=impersonator_user_id)
        active_impersonation_id = request.session.get("active_impersonation_audit_id")
        if active_impersonation_id:
            ImpersonationAudit.objects.filter(pk=active_impersonation_id, ended_at__isnull=True).update(
                ended_at=timezone.now(),
                updated_at=timezone.now(),
            )

        current_target = request.user
        login(request, impersonator)
        request.session.pop("impersonator_user_id", None)
        request.session.pop("active_impersonation_audit_id", None)
        request.session["active_user_session_id"] = None
        start_user_session(request=request, user=impersonator, auth_method=UserSession.AUTH_SESSION)
        log_security_event(
            "platform.impersonation.stop",
            request=request,
            actor=impersonator,
            target_type="user",
            target_id=str(current_target.pk),
        )
        return Response({"impersonating": False, "user_id": impersonator.id, "username": impersonator.username})
