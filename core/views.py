"""Core domain views.

These exports let callers import core-facing views from ``core.views`` while
the implementation is progressively split out of ``builder.views``.
"""

from __future__ import annotations

import copy

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from builder.views import (  # noqa: F401
    SiteViewSet as BuilderSiteViewSet,
    DashboardSummaryView,
    SiteLocaleViewSet,
    SiteObjectPermission,
    SitePermissionMixin,
    WorkspaceSearchView,
)
from cms.services import enqueue_site_revalidation
from core.compliance import request_data_deletion, request_data_export
from core.extensibility import install_app, uninstall_app
from core.models import (
    AppInstallation,
    AppRegistration,
    ConsentRecord,
    DataDeletionJob,
    DataExportJob,
    FeatureFlag,
    FeatureFlagAssignment,
    Site,
    Workspace,
)
from core.serializers import (
    AppInstallationSerializer,
    AppRegistrationSerializer,
    ConsentRecordSerializer,
    DataDeletionJobSerializer,
    DataExportJobSerializer,
    FeatureFlagAssignmentSerializer,
    FeatureFlagSerializer,
)
from domains.services import host_from_request, resolve_site_for_host
from notifications.services import trigger_webhooks
from builder.workspace_views import (
    AcceptInvitationView,
    DeclineInvitationView,
    MyWorkspacesView,
    WorkspaceViewSet,
)
from shared.auth.audit import log_security_event
from shared.policies.access import SitePermission, WorkspacePermission, has_site_permission, has_workspace_permission


class PublicRuntimeSiteMixin:
    """
    Shared site-resolution logic for read-only public runtime APIs.

    Resolution order:
    1. Explicit `?site=<id|slug>`
    2. Explicit `?domain=<host>`
    3. Request host header
    """

    def resolve_public_site(self, request, *, require_site_param: bool = False):
        site_ref = (request.query_params.get("site") or "").strip()
        if site_ref:
            if site_ref.isdigit():
                site = get_object_or_404(Site, pk=int(site_ref))
            else:
                site = get_object_or_404(Site, slug=site_ref)
            return site, None

        if require_site_param:
            raise ValidationError({"site": "This query parameter is required."})

        explicit_domain = (request.query_params.get("domain") or "").strip()
        resolution = resolve_site_for_host(explicit_domain or host_from_request(request))
        if resolution is None:
            raise NotFound("No public site is mapped to this domain.")
        return resolution.site, resolution


class SiteViewSet(BuilderSiteViewSet):
    """Core site endpoints with publish/revalidation integration."""

    def perform_update(self, serializer):
        site = serializer.instance
        previous_theme = copy.deepcopy(site.theme)
        previous_settings = copy.deepcopy(site.settings)
        previous_navigation = copy.deepcopy(site.navigation)
        previous_name = site.name
        previous_tagline = site.tagline
        previous_description = site.description

        updated_site = super().perform_update(serializer)
        site = updated_site or serializer.instance

        changed = (
            previous_theme != site.theme
            or previous_settings != site.settings
            or previous_navigation != site.navigation
            or previous_name != site.name
            or previous_tagline != site.tagline
            or previous_description != site.description
        )
        if changed:
            log_security_event(
                "site.theme_or_settings.update",
                request=self.request,
                actor=self.request.user if self.request.user.is_authenticated else None,
                target_type="site",
                target_id=str(site.pk),
                metadata={"theme_changed": previous_theme != site.theme},
            )
            enqueue_site_revalidation(
                site,
                event="site.settings.changed",
                reason="site_update",
                metadata={"site_id": site.id, "site_slug": site.slug},
            )
            trigger_webhooks(
                site,
                "site.settings.changed",
                {"site_id": site.id, "site_slug": site.slug, "event": "site.settings.changed"},
            )

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """Trigger a site-wide runtime revalidation publish event."""
        site = self.get_object()
        log_security_event(
            "site.publish",
            request=request,
            actor=request.user if request.user.is_authenticated else None,
            target_type="site",
            target_id=str(site.pk),
        )
        enqueue_site_revalidation(
            site,
            event="site.published",
            reason="manual_site_publish",
            metadata={"site_id": site.id, "site_slug": site.slug, "actor": str(request.user)},
        )
        trigger_webhooks(
            site,
            "site.published",
            {"site_id": site.id, "site_slug": site.slug, "actor": str(request.user)},
        )
        serializer = self.get_serializer(site)
        return Response(serializer.data)


class PrivacyConsentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        queryset = ConsentRecord.objects.filter(user=request.user).order_by("-created_at")
        return Response(ConsentRecordSerializer(queryset[:200], many=True).data)

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        serializer = ConsentRecordSerializer(data={**payload, "user": request.user.id})
        serializer.is_valid(raise_exception=True)
        consent = serializer.save(
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
        )
        log_security_event(
            "privacy.consent.updated",
            request=request,
            actor=request.user,
            target_type="consent",
            target_id=str(consent.id),
            metadata={"consent_type": consent.consent_type, "status": consent.status},
        )
        return Response(ConsentRecordSerializer(consent).data, status=status.HTTP_201_CREATED)


class DataExportJobViewSet(viewsets.ModelViewSet):
    serializer_class = DataExportJobSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = DataExportJob.objects.select_related("target_user", "workspace", "site").order_by("-created_at")
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(target_user=self.request.user)

    def create(self, request):
        workspace = None
        site = None
        workspace_id = request.data.get("workspace")
        site_id = request.data.get("site")
        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=workspace_id)
            if not has_workspace_permission(request.user, workspace, WorkspacePermission.VIEW):
                raise PermissionDenied("No workspace access.")
        if site_id:
            site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
            if not has_site_permission(request.user, site, SitePermission.VIEW):
                raise PermissionDenied("No site access.")
        export_job = request_data_export(requested_by=request.user, target_user=request.user, workspace=workspace, site=site)
        return Response(self.get_serializer(export_job).data, status=status.HTTP_202_ACCEPTED)


class DataDeletionJobViewSet(viewsets.ModelViewSet):
    serializer_class = DataDeletionJobSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = DataDeletionJob.objects.select_related("target_user", "workspace", "site").order_by("-created_at")
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(target_user=self.request.user)

    def create(self, request):
        reason = str((request.data or {}).get("reason") or "").strip()[:280]
        deletion_job = request_data_deletion(requested_by=request.user, target_user=request.user, reason=reason)
        log_security_event(
            "privacy.data_deletion.requested",
            request=request,
            actor=request.user,
            target_type="deletion_job",
            target_id=str(deletion_job.id),
        )
        return Response(self.get_serializer(deletion_job).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        deletion_job = self.get_object()
        if not request.user.is_superuser:
            raise PermissionDenied("Only super-admin can approve third-party deletion jobs.")
        if deletion_job.status != DataDeletionJob.STATUS_REQUESTED:
            return Response(self.get_serializer(deletion_job).data)
        deletion_job.status = DataDeletionJob.STATUS_APPROVED
        deletion_job.approved_by = request.user
        deletion_job.save(update_fields=["status", "approved_by", "updated_at"])
        request_data_deletion(
            requested_by=request.user,
            target_user=deletion_job.target_user,
            workspace=deletion_job.workspace,
            site=deletion_job.site,
            reason=deletion_job.reason,
        )
        return Response(self.get_serializer(deletion_job).data)


class AppRegistrationViewSet(viewsets.ModelViewSet):
    serializer_class = AppRegistrationSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = AppRegistration.objects.order_by("name")

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


class AppInstallationViewSet(viewsets.ModelViewSet):
    serializer_class = AppInstallationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = AppInstallation.objects.select_related("app", "workspace", "site").order_by("-created_at")
        if self.request.user.is_superuser:
            return queryset
        visible_ids: list[int] = []
        for installation in queryset:
            if installation.site_id and has_site_permission(self.request.user, installation.site, SitePermission.VIEW):
                visible_ids.append(installation.id)
            elif installation.workspace_id and has_workspace_permission(
                self.request.user, installation.workspace, WorkspacePermission.VIEW
            ):
                visible_ids.append(installation.id)
        return queryset.filter(id__in=visible_ids)

    def create(self, request):
        serializer = self.get_serializer(data=request.data if isinstance(request.data, dict) else {})
        serializer.is_valid(raise_exception=True)
        app = get_object_or_404(AppRegistration, pk=serializer.validated_data["app_id"], is_active=True)
        workspace = serializer.validated_data.get("workspace")
        site = serializer.validated_data.get("site")
        if workspace and not has_workspace_permission(request.user, workspace, WorkspacePermission.EDIT):
            raise PermissionDenied("No workspace app installation permission.")
        if site and not has_site_permission(request.user, site, SitePermission.EDIT):
            raise PermissionDenied("No site app installation permission.")
        installation = install_app(
            app=app,
            installed_by=request.user,
            workspace=workspace,
            site=site,
            scopes=serializer.validated_data.get("granted_scopes") or [],
            config=serializer.validated_data.get("config") or {},
        )
        return Response(self.get_serializer(installation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def uninstall(self, request, pk=None):
        installation = self.get_object()
        if installation.workspace_id and not has_workspace_permission(
            request.user, installation.workspace, WorkspacePermission.EDIT
        ):
            raise PermissionDenied("No workspace app uninstall permission.")
        if installation.site_id and not has_site_permission(request.user, installation.site, SitePermission.EDIT):
            raise PermissionDenied("No site app uninstall permission.")
        uninstall_app(installation)
        return Response(self.get_serializer(installation).data)


class FeatureFlagViewSet(viewsets.ModelViewSet):
    serializer_class = FeatureFlagSerializer
    queryset = FeatureFlag.objects.order_by("key")
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [permissions.IsAuthenticated()]
        return [permissions.IsAdminUser()]


class FeatureFlagAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = FeatureFlagAssignmentSerializer
    queryset = FeatureFlagAssignment.objects.select_related("flag").order_by("-created_at")
    permission_classes = [permissions.IsAdminUser]

__all__ = [
    "AppInstallationViewSet",
    "AppRegistrationViewSet",
    "AcceptInvitationView",
    "DataDeletionJobViewSet",
    "DataExportJobViewSet",
    "DeclineInvitationView",
    "DashboardSummaryView",
    "FeatureFlagAssignmentViewSet",
    "FeatureFlagViewSet",
    "MyWorkspacesView",
    "PrivacyConsentView",
    "PublicRuntimeSiteMixin",
    "SiteLocaleViewSet",
    "SiteObjectPermission",
    "SitePermissionMixin",
    "SiteViewSet",
    "WorkspaceViewSet",
    "WorkspaceSearchView",
]
