"""
Workspace / Team / Membership Views

Provides API endpoints for workspace management, member invitations,
role changes, and access control.
"""

from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from datetime import timedelta
import secrets

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Site,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from .serializers import (
    WorkspaceSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceInvitationSerializer,
    InviteMemberSerializer,
    ChangeMemberRoleSerializer,
)

User = get_user_model()


class WorkspaceViewSet(viewsets.ModelViewSet):
    """ViewSet for workspace management."""
    serializer_class = WorkspaceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _membership_for(self, workspace: Workspace):
        return workspace.memberships.filter(user=self.request.user).first()

    def _require_member_management(self, workspace: Workspace, *, owner_only: bool = False) -> None:
        if self.request.user.is_superuser:
            return
        if workspace.owner_id == self.request.user.id:
            return
        membership = self._membership_for(workspace)
        if not membership:
            raise PermissionDenied("You don't have permission to access this workspace.")
        if owner_only and membership.role != WorkspaceMembership.ROLE_OWNER:
            raise PermissionDenied("Only workspace owners can perform this action.")
        if not owner_only and not membership.can_manage_members:
            raise PermissionDenied("You don't have permission to manage this workspace.")

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Workspace.objects.none()
        return (
            Workspace.objects.select_related("owner")
            .prefetch_related("memberships")
            .filter(models.Q(owner=user) | models.Q(memberships__user=user))
            .annotate(member_count=models.Count("memberships", distinct=True))
            .annotate(site_count=models.Count("sites", distinct=True))
            .distinct()
            .order_by("name")
        )

    def perform_create(self, serializer):
        workspace = serializer.save(owner=self.request.user)
        # Auto-create owner membership
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=self.request.user,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=self.request.user,
            accepted_at=timezone.now(),
        )

    def update(self, request, *args, **kwargs):
        workspace = self.get_object()
        self._require_member_management(workspace)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        workspace = self.get_object()
        self._require_member_management(workspace)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        workspace = self.get_object()
        self._require_member_management(workspace, owner_only=True)
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        """List all members of a workspace."""
        workspace = self.get_object()
        memberships = workspace.memberships.select_related("user").order_by("role", "user__username")
        serializer = WorkspaceMembershipSerializer(memberships, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def invite(self, request, pk=None):
        """Invite a new member to the workspace."""
        workspace = self.get_object()
        self._require_member_management(workspace)

        serializer = InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].strip().lower()
        role = serializer.validated_data["role"]
        if role == WorkspaceMembership.ROLE_OWNER:
            return Response(
                {"detail": "Invitations cannot grant owner role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user already exists and is a member
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user:
            now = timezone.now()
            membership, created = WorkspaceMembership.objects.get_or_create(
                workspace=workspace,
                user=existing_user,
                defaults={
                    "role": role,
                    "invited_by": request.user,
                    "accepted_at": now,
                },
            )
            if not created:
                return Response(
                    {"detail": "This user is already a member of this workspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            workspace.invitations.filter(
                email=email,
                status=WorkspaceInvitation.STATUS_PENDING,
            ).update(
                status=WorkspaceInvitation.STATUS_ACCEPTED,
                accepted_at=now,
                updated_at=now,
            )
            return Response(
                WorkspaceMembershipSerializer(membership, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        now = timezone.now()
        reused_invitation = False
        invitation = (
            workspace.invitations.filter(
                email=email,
                status=WorkspaceInvitation.STATUS_PENDING,
                expires_at__gt=now,
            )
            .order_by("-created_at")
            .first()
        )
        if invitation:
            reused_invitation = True
            invitation.role = role
            invitation.invited_by = request.user
            invitation.expires_at = now + timedelta(days=7)
            invitation.save(update_fields=["role", "invited_by", "expires_at", "updated_at"])
        else:
            invitation = WorkspaceInvitation.objects.create(
                workspace=workspace,
                email=email,
                role=role,
                token=secrets.token_urlsafe(32),
                invited_by=request.user,
                expires_at=now + timedelta(days=7),
            )
        from .notification_services import notification_service

        notification_service.send_workspace_invitation(invitation, request.user.get_username())

        return Response(
            WorkspaceInvitationSerializer(invitation, context={"request": request}).data,
            status=status.HTTP_200_OK if reused_invitation else status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="members/(?P<member_id>[^/.]+)/role")
    def change_role(self, request, pk=None, member_id=None):
        """Change a member's role."""
        workspace = self.get_object()
        self._require_member_management(workspace)

        target_membership = get_object_or_404(workspace.memberships, pk=member_id)

        if target_membership.user_id == request.user.id:
            return Response(
                {"detail": "Use account settings to change your own role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cannot change owner's role
        if target_membership.role == WorkspaceMembership.ROLE_OWNER:
            return Response(
                {"detail": "Cannot change the owner's role."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ChangeMemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Cannot promote to owner
        new_role = serializer.validated_data["role"]
        if new_role == WorkspaceMembership.ROLE_OWNER:
            return Response(
                {"detail": "Cannot promote to owner. Use transfer ownership instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_membership.role = new_role
        target_membership.save(update_fields=["role", "updated_at"])

        return Response(WorkspaceMembershipSerializer(target_membership, context={"request": request}).data)

    @action(detail=True, methods=["delete"], url_path="members/(?P<member_id>[^/.]+)")
    def remove_member(self, request, pk=None, member_id=None):
        """Remove a member from the workspace."""
        workspace = self.get_object()
        self._require_member_management(workspace)

        target_membership = get_object_or_404(workspace.memberships, pk=member_id)

        if target_membership.user_id == request.user.id:
            return Response(
                {"detail": "You cannot remove yourself from the workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cannot remove owner
        if target_membership.role == WorkspaceMembership.ROLE_OWNER:
            return Response(
                {"detail": "Cannot remove the workspace owner."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def invitations(self, request, pk=None):
        """List pending invitations for a workspace."""
        workspace = self.get_object()
        self._require_member_management(workspace)
        invitations = workspace.invitations.filter(
            status=WorkspaceInvitation.STATUS_PENDING
        ).order_by("-created_at")
        serializer = WorkspaceInvitationSerializer(invitations, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["delete"], url_path="invitations/(?P<invitation_id>[^/.]+)")
    def cancel_invitation(self, request, pk=None, invitation_id=None):
        """Cancel a pending invitation."""
        workspace = self.get_object()
        self._require_member_management(workspace)

        invitation = get_object_or_404(
            workspace.invitations,
            pk=invitation_id,
            status=WorkspaceInvitation.STATUS_PENDING,
        )
        invitation.status = WorkspaceInvitation.STATUS_EXPIRED
        invitation.save(update_fields=["status", "updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def sites(self, request, pk=None):
        """List all sites in a workspace."""
        workspace = self.get_object()
        from .serializers import SiteSerializer
        sites = workspace.sites.prefetch_related("pages__revisions").order_by("name")
        serializer = SiteSerializer(sites, many=True, context={"request": request})
        return Response(serializer.data)


class AcceptInvitationView(APIView):
    """Accept a workspace invitation."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import InvitationAcceptThrottle

        return [InvitationAcceptThrottle()]

    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response(
                {"detail": "Invitation token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(token) < 16:
            return Response(
                {"detail": "Invitation token is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # User must be authenticated
        if not request.user.is_authenticated:
            invitation = get_object_or_404(
                WorkspaceInvitation.objects.select_related("workspace"),
                token=token,
                status=WorkspaceInvitation.STATUS_PENDING,
            )
            return Response(
                {
                    "detail": "Please log in or create an account to accept this invitation.",
                    "workspace_name": invitation.workspace.name,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        with transaction.atomic():
            invitation = get_object_or_404(
                WorkspaceInvitation.objects.select_related("workspace", "invited_by").select_for_update(),
                token=token,
                status=WorkspaceInvitation.STATUS_PENDING,
            )

            if invitation.expires_at < timezone.now():
                invitation.status = WorkspaceInvitation.STATUS_EXPIRED
                invitation.save(update_fields=["status", "updated_at"])
                return Response(
                    {"detail": "This invitation has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user_email = (request.user.email or "").strip().lower()
            if not user_email or user_email != invitation.email.lower():
                return Response(
                    {"detail": "This invitation was sent to a different email address."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            membership, created = WorkspaceMembership.objects.get_or_create(
                workspace=invitation.workspace,
                user=request.user,
                defaults={
                    "role": invitation.role,
                    "invited_by": invitation.invited_by,
                    "accepted_at": timezone.now(),
                },
            )
            if not created:
                invitation.status = WorkspaceInvitation.STATUS_ACCEPTED
                invitation.accepted_at = timezone.now()
                invitation.save(update_fields=["status", "accepted_at", "updated_at"])
                return Response(
                    {
                        "success": True,
                        "workspace": WorkspaceSerializer(
                            invitation.workspace,
                            context={"request": request},
                        ).data,
                        "role": membership.role,
                    }
                )

            invitation.status = WorkspaceInvitation.STATUS_ACCEPTED
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["status", "accepted_at", "updated_at"])

        return Response({
            "success": True,
            "workspace": WorkspaceSerializer(invitation.workspace, context={"request": request}).data,
            "role": membership.role,
        })


class DeclineInvitationView(APIView):
    """Decline a workspace invitation token."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = []

    def get_throttles(self):
        from .throttles import InvitationAcceptThrottle

        return [InvitationAcceptThrottle()]

    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response(
                {"detail": "Invitation token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(token) < 16:
            return Response(
                {"detail": "Invitation token is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            invitation = (
                WorkspaceInvitation.objects.select_for_update()
                .filter(token=token)
                .first()
            )
            if not invitation:
                return Response({"success": True})
            if invitation.status != WorkspaceInvitation.STATUS_PENDING:
                return Response({"success": True})
            if invitation.expires_at < timezone.now():
                invitation.status = WorkspaceInvitation.STATUS_EXPIRED
                invitation.save(update_fields=["status", "updated_at"])
                return Response({"success": True})

            invitation.status = WorkspaceInvitation.STATUS_DECLINED
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=["status", "accepted_at", "updated_at"])

        return Response({"success": True})


class MyWorkspacesView(APIView):
    """Get current user's workspaces."""

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        workspaces = (
            Workspace.objects.select_related("owner")
            .prefetch_related("memberships")
            .filter(models.Q(owner=request.user) | models.Q(memberships__user=request.user))
            .annotate(member_count=models.Count("memberships", distinct=True))
            .annotate(site_count=models.Count("sites", distinct=True))
            .distinct()
            .order_by("name")
        )

        serializer = WorkspaceSerializer(workspaces, many=True, context={"request": request})
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Permission Helpers
# ---------------------------------------------------------------------------

def get_user_workspace_role(user, site) -> str | None:
    """Get the user's role for a site's workspace."""
    if not user.is_authenticated:
        return None
    if not site.workspace:
        # Legacy site without workspace - allow if user is superuser
        return WorkspaceMembership.ROLE_OWNER if user.is_superuser else None
    if site.workspace.owner_id == user.id:
        return WorkspaceMembership.ROLE_OWNER
    membership = site.workspace.memberships.filter(user=user).first()
    return membership.role if membership else None


def check_site_permission(user, site, require_edit: bool = False) -> bool:
    """Check if user has permission to access/edit a site."""
    if user.is_superuser:
        return True
    role = get_user_workspace_role(user, site)
    if not role:
        return False
    if require_edit:
        return role in (WorkspaceMembership.ROLE_OWNER, WorkspaceMembership.ROLE_ADMIN, WorkspaceMembership.ROLE_EDITOR)
    return True


def check_site_manage_permission(user, site) -> bool:
    """Check if user can perform owner/admin-only actions for a site."""
    if user.is_superuser:
        return True
    role = get_user_workspace_role(user, site)
    return role in (WorkspaceMembership.ROLE_OWNER, WorkspaceMembership.ROLE_ADMIN)


def get_or_create_personal_workspace(user) -> Workspace:
    """Return the user's personal workspace, creating it on demand."""
    workspace = Workspace.objects.filter(owner=user, is_personal=True).order_by("created_at").first()
    if workspace is None:
        base_slug = slugify(f"{user.username}-workspace") or f"user-{user.pk}-workspace"
        slug = base_slug
        suffix = 2
        while Workspace.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        workspace = Workspace.objects.create(
            name=f"{user.username}'s Workspace",
            slug=slug,
            owner=user,
            is_personal=True,
        )
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            "role": WorkspaceMembership.ROLE_OWNER,
            "invited_by": user,
            "accepted_at": timezone.now(),
        },
    )
    return workspace


def resolve_workspace_for_site_creation(user, workspace_id: int | str | None = None) -> Workspace:
    """Resolve the workspace used for a newly created site."""
    if not user.is_authenticated:
        raise PermissionError("Authentication required.")
    if workspace_id in (None, ""):
        return get_or_create_personal_workspace(user)
    try:
        workspace_pk = int(workspace_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid workspace id.") from exc
    workspace = get_object_or_404(
        Workspace.objects.prefetch_related("memberships"),
        pk=workspace_pk,
    )
    if not check_site_permission(user, Site(workspace=workspace), require_edit=True):
        raise PermissionError("You don't have permission to create sites in this workspace.")
    WorkspaceMembership.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            "role": WorkspaceMembership.ROLE_OWNER if workspace.owner_id == user.id else WorkspaceMembership.ROLE_EDITOR,
            "invited_by": user,
            "accepted_at": timezone.now(),
        },
    )
    return workspace


def filter_sites_by_permission(user, queryset):
    """Filter a Site queryset to only include sites the user can access."""
    if user.is_superuser:
        return queryset
    if not user.is_authenticated:
        return queryset.none()
    # Legacy workspace-less sites remain visible to superusers only.
    return queryset.filter(
        models.Q(workspace__memberships__user=user) | models.Q(workspace__owner=user)
    ).distinct()


def get_user_workspaces(user):
    """Return workspaces the user can access."""
    if not user.is_authenticated:
        return Workspace.objects.none()
    if user.is_superuser:
        return Workspace.objects.all().order_by("name")
    return Workspace.objects.filter(
        models.Q(owner=user) | models.Q(memberships__user=user)
    ).distinct().order_by("name")
