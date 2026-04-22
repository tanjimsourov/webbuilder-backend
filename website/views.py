from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Site
from domains.models import Domain
from notifications.services import trigger_webhooks
from shared.policies.access import SitePermission, has_site_permission
from website.serializers import WebsiteDomainSerializer, WebsitePublishStatusSerializer, WebsiteSettingsSerializer
from website.services import (
    update_deployment_metadata,
    update_website_settings,
    verify_site_domain,
    website_domain_records,
    website_publish_status,
    website_robots,
    website_settings_for_site,
    website_sitemap,
)


class WebsiteSitePermissionMixin:
    permission_classes = [permissions.IsAuthenticated]

    def _resolve_site(self, request, site_id: int, *, require_edit: bool = False) -> Site:
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
        permission = SitePermission.EDIT if require_edit else SitePermission.VIEW
        if not has_site_permission(request.user, site, permission):
            raise PermissionDenied("You don't have permission to access this site.")
        return site


class WebsiteSettingsView(WebsiteSitePermissionMixin, APIView):
    def get(self, request, site_id: int):
        site = self._resolve_site(request, site_id, require_edit=False)
        payload = website_settings_for_site(site)
        return Response(WebsiteSettingsSerializer(payload).data)

    def put(self, request, site_id: int):
        site = self._resolve_site(request, site_id, require_edit=True)
        updated = update_website_settings(site, request.data if isinstance(request.data, dict) else {})
        trigger_webhooks(site, "site.settings.updated", {"site_id": site.id})
        return Response(WebsiteSettingsSerializer(updated).data)

    def patch(self, request, site_id: int):
        return self.put(request, site_id)


class WebsitePublishStatusView(WebsiteSitePermissionMixin, APIView):
    def get(self, request, site_id: int):
        site = self._resolve_site(request, site_id, require_edit=False)
        payload = website_publish_status(site)
        return Response(WebsitePublishStatusSerializer(payload).data)

    def post(self, request, site_id: int):
        site = self._resolve_site(request, site_id, require_edit=True)
        payload = update_deployment_metadata(site, request.data if isinstance(request.data, dict) else {})
        trigger_webhooks(site, "site.deployment.updated", {"site_id": site.id, "deployment": payload.get("deployment", {})})
        return Response(WebsitePublishStatusSerializer(payload).data)


class WebsiteDomainsView(WebsiteSitePermissionMixin, APIView):
    def get(self, request, site_id: int):
        site = self._resolve_site(request, site_id, require_edit=False)
        payload = website_domain_records(site)
        return Response(WebsiteDomainSerializer(payload, many=True).data)


class WebsiteDomainVerifyView(WebsiteSitePermissionMixin, APIView):
    def post(self, request, site_id: int, domain_id: int):
        site = self._resolve_site(request, site_id, require_edit=True)
        domain = get_object_or_404(Domain.objects.filter(site=site), pk=domain_id)
        payload = verify_site_domain(domain, check_now=bool(request.data.get("check_now", True)))
        trigger_webhooks(site, "site.domain.verification", {"site_id": site.id, "domain_id": domain.id, "status": payload["status"]})
        return Response(payload)


class WebsiteRobotsView(WebsiteSitePermissionMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, site_id: int):
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
        payload = website_robots(site, scheme=request.scheme, host=request.get_host())
        response = Response(payload)
        patch_cache_control(response, public=True, max_age=300, s_maxage=900, stale_while_revalidate=300)
        return response


class WebsiteSitemapView(WebsiteSitePermissionMixin, APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, site_id: int):
        site = get_object_or_404(Site.objects.select_related("workspace"), pk=site_id)
        payload = website_sitemap(site)
        response = Response({"site": site.id, "entries": payload}, status=status.HTTP_200_OK)
        patch_cache_control(response, public=True, max_age=300, s_maxage=900, stale_while_revalidate=300)
        return response
