"""CMS domain view wrappers.

These classes currently inherit behavior from ``builder.views`` and provide
the app-local extension points for CMS logic.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.cache import patch_cache_control
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from builder.views import (
    AssetUsageReferenceViewSet as BuilderAssetUsageReferenceViewSet,
    BlockTemplateViewSet as BuilderBlockTemplateViewSet,
    MediaAssetViewSet as BuilderMediaAssetViewSet,
    MediaFolderViewSet as BuilderMediaFolderViewSet,
    NavigationMenuViewSet as BuilderNavigationMenuViewSet,
    PageExperimentViewSet,
    PageRevisionViewSet,
    PageReviewCommentViewSet,
    PageReviewViewSet,
    PageTranslationViewSet as BuilderPageTranslationViewSet,
    PageViewSet as BuilderPageViewSet,
    PreviewTokenViewSet as BuilderPreviewTokenViewSet,
    PublishSnapshotViewSet as BuilderPublishSnapshotViewSet,
    ReusableSectionViewSet as BuilderReusableSectionViewSet,
    RobotsTxtViewSet as BuilderRobotsTxtViewSet,
    SiteShellViewSet as BuilderSiteShellViewSet,
    ThemeTemplateViewSet as BuilderThemeTemplateViewSet,
    URLRedirectViewSet as BuilderURLRedirectViewSet,
    public_page,
    public_robots,
    public_sitemap,
)
from builder.jobs import queue_search_index
from builder.serializers import BuilderSaveSerializer
from cms.serializers import (
    PublicRuntimeMenuSerializer,
    PublicRuntimePageSerializer,
    PublicRuntimeSiteIdentitySerializer,
    PublicRuntimeSiteSettingsSerializer,
    PublicRuntimeSitemapEntrySerializer,
)
from cms.models import PublishSnapshot
from cms.services import (
    apply_page_payload,
    build_public_meta_payload,
    build_public_page_payload,
    enqueue_navigation_revalidation,
    publish_page_content,
    public_robots_payload,
    public_site_capabilities,
    public_site_settings,
    public_sitemap_entries,
    schedule_page_publication,
    resolve_public_page,
    sync_homepage_state,
    unpublish_page_content,
)
from core.views import PublicRuntimeSiteMixin
from domains.services import primary_public_domain_for_site
from notifications.services import trigger_webhooks
from shared.auth.audit import log_security_event


class PageViewSet(BuilderPageViewSet):
    """CMS page endpoints."""

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        page = self.get_object()
        if request.data:
            serializer = BuilderSaveSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            apply_page_payload(page, serializer.validated_data)
            sync_homepage_state(page)
        try:
            result = publish_page_content(page, actor=str(request.user), reason="manual_publish")
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            raise ValidationError(detail)
        queue_search_index("page", page.id)
        PublishSnapshot.objects.create(
            site=page.site,
            target_type=PublishSnapshot.TARGET_PAGE,
            target_id=page.id,
            revision_label="Published snapshot",
            snapshot={
                "title": page.title,
                "slug": page.slug,
                "path": page.path,
                "builder_data": page.builder_data,
                "seo": page.seo,
                "page_settings": page.page_settings,
                "html": page.html,
                "css": page.css,
                "js": page.js,
            },
            actor=request.user if request.user.is_authenticated else None,
            metadata={"source": "cms.page.publish"},
        )
        log_security_event(
            "site.publish",
            request=request,
            actor=request.user if request.user.is_authenticated else None,
            target_type="page",
            target_id=str(page.pk),
            metadata={"site_id": page.site_id, "path": page.path},
        )
        serializer = self.get_serializer(result["page"])
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def unpublish(self, request, pk=None):
        page = self.get_object()
        result = unpublish_page_content(page, actor=str(request.user), reason="manual_unpublish")
        queue_search_index("page", page.id)
        PublishSnapshot.objects.create(
            site=page.site,
            target_type=PublishSnapshot.TARGET_PAGE,
            target_id=page.id,
            revision_label="Unpublished snapshot",
            snapshot={
                "title": page.title,
                "slug": page.slug,
                "path": page.path,
                "builder_data": page.builder_data,
                "seo": page.seo,
                "page_settings": page.page_settings,
                "html": page.html,
                "css": page.css,
                "js": page.js,
            },
            actor=request.user if request.user.is_authenticated else None,
            metadata={"source": "cms.page.unpublish"},
        )
        log_security_event(
            "site.unpublish",
            request=request,
            actor=request.user if request.user.is_authenticated else None,
            target_type="page",
            target_id=str(page.pk),
            metadata={"site_id": page.site_id, "path": page.path},
        )
        serializer = self.get_serializer(result["page"])
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        page = self.get_object()
        raw_scheduled_at = request.data.get("scheduled_at")
        if not raw_scheduled_at:
            raise ValidationError({"scheduled_at": "This field is required."})
        scheduled_at = parse_datetime(str(raw_scheduled_at))
        if scheduled_at is None:
            raise ValidationError({"scheduled_at": "Invalid ISO datetime format."})
        if timezone.is_naive(scheduled_at):
            scheduled_at = timezone.make_aware(scheduled_at, timezone.get_current_timezone())
        if scheduled_at <= timezone.now():
            raise ValidationError({"scheduled_at": "Scheduled time must be in the future."})

        try:
            schedule_page_publication(page, scheduled_at)
        except ValueError as exc:
            raise ValidationError({"scheduled_at": str(exc)})
        trigger_webhooks(
            page.site,
            "page.scheduled",
            {"page_id": page.id, "title": page.title, "path": page.path, "scheduled_at": scheduled_at.isoformat()},
        )
        serializer = self.get_serializer(page)
        return Response(serializer.data)


PageTranslationViewSet = BuilderPageTranslationViewSet
AssetUsageReferenceViewSet = BuilderAssetUsageReferenceViewSet
MediaAssetViewSet = BuilderMediaAssetViewSet
MediaFolderViewSet = BuilderMediaFolderViewSet
BlockTemplateViewSet = BuilderBlockTemplateViewSet
ReusableSectionViewSet = BuilderReusableSectionViewSet
ThemeTemplateViewSet = BuilderThemeTemplateViewSet
SiteShellViewSet = BuilderSiteShellViewSet
PublishSnapshotViewSet = BuilderPublishSnapshotViewSet
PreviewTokenViewSet = BuilderPreviewTokenViewSet
URLRedirectViewSet = BuilderURLRedirectViewSet


class NavigationMenuViewSet(BuilderNavigationMenuViewSet):
    """Navigation menu endpoints."""

    def perform_create(self, serializer):
        menu = super().perform_create(serializer)
        enqueue_navigation_revalidation(menu, reason="navigation_created")
        trigger_webhooks(
            menu.site,
            "site.navigation.changed",
            {"menu_id": menu.id, "menu_slug": menu.slug, "action": "created"},
        )

    def perform_update(self, serializer):
        menu = super().perform_update(serializer)
        enqueue_navigation_revalidation(menu, reason="navigation_updated")
        trigger_webhooks(
            menu.site,
            "site.navigation.changed",
            {"menu_id": menu.id, "menu_slug": menu.slug, "action": "updated"},
        )

    def perform_destroy(self, instance):
        site = instance.site
        menu_id = instance.id
        menu_slug = instance.slug
        enqueue_navigation_revalidation(instance, reason="navigation_deleted")
        super().perform_destroy(instance)
        trigger_webhooks(
            site,
            "site.navigation.changed",
            {"menu_id": menu_id, "menu_slug": menu_slug, "action": "deleted"},
        )


RobotsTxtViewSet = BuilderRobotsTxtViewSet


class PublicRuntimeBaseView(PublicRuntimeSiteMixin, APIView):
    """Base class for unauthenticated read-only runtime APIs."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class PublicRuntimeSiteLookupView(PublicRuntimeBaseView):
    """
    Resolve a site from domain/host and return renderer-safe site identity.

    This endpoint is the first call the Next.js runtime makes.
    """

    def get(self, request):
        site, resolution = self.resolve_public_site(request)
        locales = site.locales.filter(is_enabled=True).order_by("-is_default", "code")
        canonical_domain = (
            (resolution.canonical_domain if resolution else "")
            or primary_public_domain_for_site(site)
        )
        payload = {
            "id": site.id,
            "slug": site.slug,
            "name": site.name,
            "tagline": site.tagline,
            "description": site.description,
            "matched_domain": resolution.matched_domain if resolution else "",
            "canonical_domain": canonical_domain,
            "resolution_source": resolution.source if resolution else "site",
            "locales": [
                {
                    "code": locale.code,
                    "direction": locale.direction,
                    "is_default": locale.is_default,
                }
                for locale in locales
            ],
            "capabilities": public_site_capabilities(site),
        }
        serializer = PublicRuntimeSiteIdentitySerializer(payload)
        response = Response({"site": serializer.data})
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=120)
        return response


class PublicRuntimePageLookupView(PublicRuntimeBaseView):
    """
    Lookup a published page by `site + path` and optional locale.

    Returns stable render data, route metadata, and computed SEO tags.
    """

    def get(self, request):
        site, resolution = self.resolve_public_site(request)
        page_path = (request.query_params.get("path") or "").strip()
        locale_code = (request.query_params.get("locale") or "").strip()
        if not page_path:
            raise ValidationError({"path": "This query parameter is required."})

        page_resolution = resolve_public_page(site, page_path, locale_code=locale_code)
        if not page_resolution.found:
            raise NotFound("Published page not found for the requested path.")

        page_payload = build_public_page_payload(page_resolution)
        canonical_domain = (
            (resolution.canonical_domain if resolution else "")
            or primary_public_domain_for_site(site)
        )
        meta_payload = build_public_meta_payload(
            site=site,
            page_payload=page_payload,
            canonical_domain=canonical_domain,
            scheme=request.scheme,
        )
        serializer = PublicRuntimePageSerializer(page_payload)
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "route": {
                    "requested_path": page_path,
                    "resolved_path": page_resolution.normalized_path,
                    "requested_locale": locale_code,
                    "resolved_locale": page_payload.get("locale", ""),
                    "is_translation": page_resolution.is_translation,
                    "builder_schema_version": page_resolution.schema_version,
                },
                "page": serializer.data,
                "meta": meta_payload,
            }
        )
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=120)
        return response


class PublicRuntimeNavigationView(PublicRuntimeBaseView):
    """Return active menus and legacy site navigation for the runtime."""

    def get(self, request):
        site, _ = self.resolve_public_site(request)
        menus = site.navigation_menus.filter(is_active=True).order_by("location", "name")
        serializer = PublicRuntimeMenuSerializer(menus, many=True)
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "menus": serializer.data,
                "legacy_navigation": site.navigation if isinstance(site.navigation, list) else [],
            }
        )
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=120)
        return response


class PublicRuntimeSiteSettingsView(PublicRuntimeBaseView):
    """Return public theme/settings needed by the renderer shell."""

    def get(self, request):
        site, _ = self.resolve_public_site(request)
        payload = {
            "site": {"id": site.id, "slug": site.slug},
            "settings": public_site_settings(site),
        }
        serializer = PublicRuntimeSiteSettingsSerializer(payload)
        response = Response(serializer.data)
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=120)
        return response


class PublicRuntimeSEOView(PublicRuntimeBaseView):
    """Resolve SEO/meta values for a published page path."""

    def get(self, request):
        site, resolution = self.resolve_public_site(request)
        page_path = (request.query_params.get("path") or "").strip() or "/"
        locale_code = (request.query_params.get("locale") or "").strip()
        page_resolution = resolve_public_page(site, page_path, locale_code=locale_code)
        if not page_resolution.found:
            raise NotFound("Published page not found for SEO resolution.")

        page_payload = build_public_page_payload(page_resolution)
        canonical_domain = (
            (resolution.canonical_domain if resolution else "")
            or primary_public_domain_for_site(site)
        )
        meta_payload = build_public_meta_payload(
            site=site,
            page_payload=page_payload,
            canonical_domain=canonical_domain,
            scheme=request.scheme,
        )
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "path": page_resolution.normalized_path,
                "locale": page_payload.get("locale", ""),
                "meta": meta_payload,
                "seo": page_payload.get("seo", {}),
            }
        )
        patch_cache_control(response, public=True, max_age=60, s_maxage=300, stale_while_revalidate=120)
        return response


class PublicRuntimeRobotsView(PublicRuntimeBaseView):
    """Return robots payload used by the runtime edge/app server."""

    def get(self, request):
        site, resolution = self.resolve_public_site(request)
        canonical_domain = (
            (resolution.canonical_domain if resolution else "")
            or primary_public_domain_for_site(site)
        )
        if canonical_domain:
            sitemap_url = f"{request.scheme}://{canonical_domain}/sitemap.xml"
        else:
            sitemap_url = request.build_absolute_uri("/sitemap.xml")
        payload = public_robots_payload(site, sitemap_url=sitemap_url)
        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                **payload,
            }
        )
        patch_cache_control(response, public=True, max_age=300, s_maxage=900, stale_while_revalidate=300)
        return response


class PublicRuntimeSitemapView(PublicRuntimeBaseView):
    """Return JSON sitemap entries for published public content."""

    def get(self, request):
        site, resolution = self.resolve_public_site(request)
        entries = public_sitemap_entries(site)
        serialized_entries = PublicRuntimeSitemapEntrySerializer(entries, many=True).data

        canonical_domain = (
            (resolution.canonical_domain if resolution else "")
            or primary_public_domain_for_site(site)
        )
        if canonical_domain:
            base_url = f"{request.scheme}://{canonical_domain}"
            for entry in serialized_entries:
                entry["absolute_url"] = f"{base_url}{entry['path']}"

        response = Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "entries": serialized_entries,
            }
        )
        patch_cache_control(response, public=True, max_age=300, s_maxage=900, stale_while_revalidate=300)
        return response


__all__ = [
    "BlockTemplateViewSet",
    "AssetUsageReferenceViewSet",
    "MediaAssetViewSet",
    "MediaFolderViewSet",
    "NavigationMenuViewSet",
    "PreviewTokenViewSet",
    "PublishSnapshotViewSet",
    "PageExperimentViewSet",
    "PageRevisionViewSet",
    "PageReviewCommentViewSet",
    "PageReviewViewSet",
    "PageTranslationViewSet",
    "PageViewSet",
    "ReusableSectionViewSet",
    "RobotsTxtViewSet",
    "SiteShellViewSet",
    "ThemeTemplateViewSet",
    "URLRedirectViewSet",
    "public_page",
    "public_robots",
    "public_sitemap",
    "PublicRuntimeNavigationView",
    "PublicRuntimePageLookupView",
    "PublicRuntimeRobotsView",
    "PublicRuntimeSEOView",
    "PublicRuntimeSiteLookupView",
    "PublicRuntimeSiteSettingsView",
    "PublicRuntimeSitemapView",
]
