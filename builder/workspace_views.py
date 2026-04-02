"""
Workspace / Team / Membership Views

Provides API endpoints for workspace management, member invitations,
role changes, and access control.
"""

from django.contrib.auth import get_user_model
from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from datetime import timedelta
import secrets

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
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

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Workspace.objects.none()
        # Return workspaces where user is owner or member
        return Workspace.objects.filter(
            models.Q(owner=user) | models.Q(memberships__user=user)
        ).distinct().order_by("name")

    def perform_create(self, serializer):
        workspace = serializer.save(owner=self.request.user)
        # Auto-create owner membership
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=self.request.user,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=self.request.user,
        )

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

        # Check permission
        membership = workspace.memberships.filter(user=request.user).first()
        if not membership or not membership.can_manage_members:
            return Response(
                {"detail": "You don't have permission to invite members."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        role = serializer.validated_data["role"]

        # Check if user already exists and is a member
        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            if workspace.memberships.filter(user=existing_user).exists():
                return Response(
                    {"detail": "This user is already a member of this workspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Add directly if user exists
            new_membership = WorkspaceMembership.objects.create(
                workspace=workspace,
                user=existing_user,
                role=role,
                invited_by=request.user,
            )
            return Response(
                WorkspaceMembershipSerializer(new_membership, context={"request": request}).data,
                status=status.HTTP_201_CREATED,
            )

        # Create invitation for non-existing user
        invitation = WorkspaceInvitation.objects.create(
            workspace=workspace,
            email=email,
            role=role,
            token=secrets.token_urlsafe(32),
            invited_by=request.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        from .notification_services import notification_service

        notification_service.send_workspace_invitation(invitation, request.user.get_username())

        return Response(
            WorkspaceInvitationSerializer(invitation, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="members/(?P<member_id>[^/.]+)/role")
    def change_role(self, request, pk=None, member_id=None):
        """Change a member's role."""
        workspace = self.get_object()

        # Check permission
        current_membership = workspace.memberships.filter(user=request.user).first()
        if not current_membership or not current_membership.can_manage_members:
            return Response(
                {"detail": "You don't have permission to change roles."},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_membership = get_object_or_404(workspace.memberships, pk=member_id)

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

        # Check permission
        current_membership = workspace.memberships.filter(user=request.user).first()
        if not current_membership or not current_membership.can_manage_members:
            return Response(
                {"detail": "You don't have permission to remove members."},
                status=status.HTTP_403_FORBIDDEN,
            )

        target_membership = get_object_or_404(workspace.memberships, pk=member_id)

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
        invitations = workspace.invitations.filter(
            status=WorkspaceInvitation.STATUS_PENDING
        ).order_by("-created_at")
        serializer = WorkspaceInvitationSerializer(invitations, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["delete"], url_path="invitations/(?P<invitation_id>[^/.]+)")
    def cancel_invitation(self, request, pk=None, invitation_id=None):
        """Cancel a pending invitation."""
        workspace = self.get_object()

        # Check permission
        membership = workspace.memberships.filter(user=request.user).first()
        if not membership or not membership.can_manage_members:
            return Response(
                {"detail": "You don't have permission to cancel invitations."},
                status=status.HTTP_403_FORBIDDEN,
            )

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
        token = request.data.get("token")
        if not token:
            return Response(
                {"detail": "Invitation token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation = get_object_or_404(
            WorkspaceInvitation,
            token=token,
            status=WorkspaceInvitation.STATUS_PENDING,
        )

        # Check if expired
        if invitation.expires_at < timezone.now():
            invitation.status = WorkspaceInvitation.STATUS_EXPIRED
            invitation.save(update_fields=["status", "updated_at"])
            return Response(
                {"detail": "This invitation has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # User must be authenticated
        if not request.user.is_authenticated:
            return Response(
                {
                    "detail": "Please log in or create an account to accept this invitation.",
                    "workspace_name": invitation.workspace.name,
                    "email": invitation.email,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check email matches (optional - can be relaxed)
        if request.user.email and request.user.email.lower() != invitation.email.lower():
            return Response(
                {"detail": "This invitation was sent to a different email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create membership
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
            return Response(
                {"detail": "You are already a member of this workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark invitation as accepted
        invitation.status = WorkspaceInvitation.STATUS_ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at", "updated_at"])

        return Response({
            "success": True,
            "workspace": WorkspaceSerializer(invitation.workspace, context={"request": request}).data,
            "role": membership.role,
        })


class MyWorkspacesView(APIView):
    """Get current user's workspaces."""

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        workspaces = Workspace.objects.filter(
            models.Q(owner=request.user) | models.Q(memberships__user=request.user)
        ).distinct().order_by("name")

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
