"""Core domain views.

These exports let callers import core-facing views from ``core.views`` while
the implementation is progressively split out of ``builder.views``.
"""

from __future__ import annotations

import copy

from django.shortcuts import get_object_or_404
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from builder.views import (  # noqa: F401
    SiteViewSet as BuilderSiteViewSet,
    DashboardSummaryView,
    SiteLocaleViewSet,
    SiteObjectPermission,
    SitePermissionMixin,
    WorkspaceSearchView,
)
from cms.services import enqueue_site_revalidation
from core.models import Site
from domains.services import host_from_request, resolve_site_for_host
from notifications.services import trigger_webhooks
from builder.workspace_views import AcceptInvitationView, MyWorkspacesView, WorkspaceViewSet


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

__all__ = [
    "AcceptInvitationView",
    "DashboardSummaryView",
    "MyWorkspacesView",
    "PublicRuntimeSiteMixin",
    "SiteLocaleViewSet",
    "SiteObjectPermission",
    "SitePermissionMixin",
    "SiteViewSet",
    "WorkspaceViewSet",
    "WorkspaceSearchView",
]
