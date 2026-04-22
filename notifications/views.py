"""Notifications domain view wrappers.

Email hosting views are re-exported here for backwards compatibility with
existing URL imports.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.models import Site, Workspace
from notifications.models import Notification, WebhookEndpoint, WebhookEndpointDelivery
from notifications.serializers import NotificationSerializer, WebhookEndpointDeliverySerializer, WebhookEndpointSerializer
from shared.policies.access import SitePermission, WorkspacePermission, has_site_permission, has_workspace_permission

from builder.views import WebhookViewSet as BuilderWebhookViewSet
from email_hosting.views import (
    EmailDomainCreateView,
    EmailDomainViewSet,
    EmailProvisioningTaskViewSet,
    MailAliasViewSet,
    MailboxCreateView,
    MailboxViewSet,
)


WebhookViewSet = BuilderWebhookViewSet


class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = Notification.objects.order_by("-created_at")
        user = self.request.user
        if user.is_superuser:
            return queryset
        return queryset.filter(recipient=user)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.status = Notification.STATUS_READ
        notification.read_at = notification.read_at or notification.updated_at
        notification.save(update_fields=["status", "read_at", "updated_at"])
        return Response(self.get_serializer(notification).data)


class WebhookEndpointViewSet(viewsets.ModelViewSet):
    serializer_class = WebhookEndpointSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = WebhookEndpoint.objects.order_by("-created_at")
        user = self.request.user
        if user.is_superuser:
            return queryset
        site_ids = [
            site.id
            for site in Site.objects.select_related("workspace")
            if has_site_permission(user, site, SitePermission.EDIT)
        ]
        workspace_ids = [
            workspace.id
            for workspace in Workspace.objects.all()
            if has_workspace_permission(user, workspace, WorkspacePermission.EDIT)
        ]
        return queryset.filter(site_id__in=site_ids) | queryset.filter(workspace_id__in=workspace_ids)

    def perform_create(self, serializer):
        data = serializer.validated_data
        site = data.get("site")
        workspace = data.get("workspace")
        if site and not has_site_permission(self.request.user, site, SitePermission.EDIT):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("No site webhook permission.")
        if workspace and not has_workspace_permission(self.request.user, workspace, WorkspacePermission.EDIT):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("No workspace webhook permission.")
        serializer.save()


class WebhookEndpointDeliveryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WebhookEndpointDeliverySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        endpoint_id = self.request.query_params.get("endpoint")
        queryset = WebhookEndpointDelivery.objects.select_related("endpoint").order_by("-created_at")
        if endpoint_id:
            queryset = queryset.filter(endpoint_id=endpoint_id)
        if self.request.user.is_superuser:
            return queryset

        visible_endpoint_ids = []
        for endpoint in WebhookEndpoint.objects.select_related("site", "workspace"):
            site = endpoint.site
            workspace = endpoint.workspace
            if site and has_site_permission(self.request.user, site, SitePermission.VIEW):
                visible_endpoint_ids.append(endpoint.id)
                continue
            if workspace and has_workspace_permission(self.request.user, workspace, WorkspacePermission.VIEW):
                visible_endpoint_ids.append(endpoint.id)
        return queryset.filter(endpoint_id__in=visible_endpoint_ids)


__all__ = [
    "EmailDomainCreateView",
    "EmailDomainViewSet",
    "EmailProvisioningTaskViewSet",
    "MailAliasViewSet",
    "MailboxCreateView",
    "MailboxViewSet",
    "NotificationViewSet",
    "WebhookEndpointDeliveryViewSet",
    "WebhookEndpointViewSet",
    "WebhookViewSet",
]
