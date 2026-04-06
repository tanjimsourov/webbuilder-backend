"""CMS domain service wrappers.

This module is the app-level home for page and media business logic.
Current implementations call into legacy ``builder.services`` while the
monolith is being split by domain.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urljoin, urlparse
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from blog.models import Post
from commerce.models import Product
from cms.page_schema import (
    PAGE_SCHEMA_VERSION,
    extract_page_summary,
    extract_render_cache,
    normalize_page_content,
    SUPPORTED_SECTION_DATA_SOURCE_TYPES,
    section_component_registry,
)
from cms.models import Page, PageTranslation, RobotsTxt
from cms.localization import select_best_locale
from core.models import Site, SiteLocale
from forms.models import Form
from builder import services as builder_services

BASE_BLOCK_CSS = builder_services.BASE_BLOCK_CSS
ensure_global_block_templates = builder_services.ensure_global_block_templates
ensure_site_cms_modules = builder_services.ensure_site_cms_modules
normalize_page_path = builder_services.normalize_page_path
preview_url_for_page = builder_services.preview_url_for_page
preview_url_for_page_translation = builder_services.preview_url_for_page_translation
sync_homepage_state = builder_services.sync_homepage_state

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicPageResolution:
    """Published page lookup result used by public runtime endpoints."""

    site: Site
    normalized_path: str
    locale: SiteLocale | None
    page: Page | None
    translation: PageTranslation | None

    @property
    def found(self) -> bool:
        return self.page is not None

    @property
    def is_translation(self) -> bool:
        return self.translation is not None

    @property
    def effective_locale(self) -> SiteLocale | None:
        if self.translation:
            return self.translation.locale
        return self.locale

    @property
    def schema_version(self) -> int:
        source = self.translation if self.translation else self.page
        return int(getattr(source, "builder_schema_version", PAGE_SCHEMA_VERSION) or PAGE_SCHEMA_VERSION)


def _is_live_content_q(field_prefix: str = "") -> Q:
    now = timezone.now()
    published_at_field = f"{field_prefix}published_at"
    return Q(**{f"{published_at_field}__isnull": True}) | Q(**{f"{published_at_field}__lte": now})


def normalize_runtime_page_path(raw_path: str | None, *, site_slug: str = "") -> str:
    """Normalize incoming runtime page paths to the canonical stored format."""
    value = (raw_path or "").strip()
    if not value:
        return "/"

    parsed = urlsplit(value)
    path = (parsed.path or value).strip()
    if not path or path == "/":
        return "/"

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2 and segments[0] == "preview" and site_slug and segments[1] == site_slug:
        segments = segments[2:]
        if segments and re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", segments[0]):
            # Preview/localized editor paths can include a locale segment we do not store in `Page.path`.
            segments = segments[1:]
        path = "/" if not segments else f"/{'/'.join(segments)}/"

    return normalize_page_path(path, False) if path != "/" else "/"


def resolve_public_locale(site: Site, locale_code: str | None) -> SiteLocale | None:
    """Resolve the best enabled locale for public runtime requests."""
    locales = list(site.locales.filter(is_enabled=True).order_by("-is_default", "code"))
    if not locales:
        return None
    if locale_code:
        try:
            best = select_best_locale(locale_code, [locale.code for locale in locales])
        except ValueError:
            best = None
        if best:
            for locale in locales:
                if locale.code == best:
                    return locale
    for locale in locales:
        if locale.is_default:
            return locale
    return locales[0]


def resolve_public_page(site: Site, page_path: str | None, locale_code: str | None = None) -> PublicPageResolution:
    """
    Resolve a published page for `site + path` with optional locale fallback.

    Visibility guarantees:
    - Base pages must be `status=published`.
    - Translations must be `status=published` and enabled locale.
    - Future-dated `published_at` content is excluded.
    """
    normalized_path = normalize_runtime_page_path(page_path, site_slug=site.slug)
    locale = resolve_public_locale(site, locale_code)

    translation_queryset = (
        PageTranslation.objects.select_related("page", "locale")
        .filter(
            page__site=site,
            status=PageTranslation.STATUS_PUBLISHED,
            page__status=Page.STATUS_PUBLISHED,
            locale__is_enabled=True,
        )
        .filter(_is_live_content_q(), _is_live_content_q("page__"))
    )

    if locale and not locale.is_default:
        localized = translation_queryset.filter(locale=locale, path=normalized_path).first()
        if localized:
            return PublicPageResolution(
                site=site,
                normalized_path=normalized_path,
                locale=locale,
                page=localized.page,
                translation=localized,
            )

    if normalized_path != "/":
        translated_path_match = translation_queryset.filter(path=normalized_path).order_by("-locale__is_default", "id").first()
        if translated_path_match:
            return PublicPageResolution(
                site=site,
                normalized_path=normalized_path,
                locale=translated_path_match.locale,
                page=translated_path_match.page,
                translation=translated_path_match,
            )

    pages = site.pages.filter(status=Page.STATUS_PUBLISHED).filter(_is_live_content_q())
    page = pages.filter(path=normalized_path).first()
    if page is None and normalized_path == "/":
        page = pages.filter(is_homepage=True).first()
    if page is None:
        return PublicPageResolution(
            site=site,
            normalized_path=normalized_path,
            locale=locale,
            page=None,
            translation=None,
        )

    translation = None
    if locale and not locale.is_default:
        translation = (
            page.translations.select_related("locale")
            .filter(status=PageTranslation.STATUS_PUBLISHED, locale=locale)
            .filter(_is_live_content_q())
            .first()
        )
    return PublicPageResolution(
        site=site,
        normalized_path=normalized_path,
        locale=locale,
        page=page,
        translation=translation,
    )


def build_public_page_payload(resolution: PublicPageResolution) -> dict[str, Any]:
    """Build a renderer-friendly payload from a published page resolution."""
    if not resolution.page:
        raise ValueError("Cannot build page payload when no page was resolved.")

    source = resolution.translation if resolution.translation else resolution.page
    source_builder_data = source.builder_data if isinstance(source.builder_data, dict) else {}
    builder_meta = source_builder_data.get("metadata") if isinstance(source_builder_data, dict) else {}
    builder_seo = source_builder_data.get("seo") if isinstance(source_builder_data, dict) else {}
    render_cache = extract_render_cache(
        source_builder_data,
        html=source.html,
        css=source.css,
        js=source.js,
    )

    title = (
        str(builder_meta.get("title") or "").strip()
        if isinstance(builder_meta, dict) and str(builder_meta.get("title") or "").strip()
        else source.title
    )
    seo_payload = builder_seo if isinstance(builder_seo, dict) and builder_seo else (source.seo or {})
    page_settings = source.page_settings if isinstance(source.page_settings, dict) else {}
    sections_payload = source_builder_data.get("sections") if isinstance(source_builder_data.get("sections"), list) else []
    section_contract_raw = (
        source_builder_data.get("section_contract")
        if isinstance(source_builder_data.get("section_contract"), dict)
        else {}
    )
    section_contract = {
        "version": int(section_contract_raw.get("version") or 1),
        "registry": str(section_contract_raw.get("registry") or "nextjs"),
        "allowed_data_sources": (
            section_contract_raw.get("allowed_data_sources")
            if isinstance(section_contract_raw.get("allowed_data_sources"), list)
            else sorted(SUPPORTED_SECTION_DATA_SOURCE_TYPES)
        ),
    }
    locale = resolution.effective_locale

    return {
        "id": source.id,
        "page_id": resolution.page.id,
        "translation_id": source.id if resolution.translation else None,
        "title": title,
        "path": resolution.normalized_path,
        "is_homepage": bool(resolution.page.is_homepage),
        "locale": locale.code if locale else "",
        "is_translation": bool(resolution.translation),
        "builder_schema_version": int(source.builder_schema_version or PAGE_SCHEMA_VERSION),
        "builder_data": source_builder_data,
        "section_contract": section_contract,
        "sections": sections_payload,
        "component_registry": section_component_registry(),
        "page_settings": page_settings,
        "seo": seo_payload if isinstance(seo_payload, dict) else {},
        "html": render_cache["html"],
        "css": render_cache["css"],
        "js": render_cache["js"],
        "updated_at": source.updated_at,
    }


def build_public_meta_payload(
    *,
    site: Site,
    page_payload: dict[str, Any],
    canonical_domain: str = "",
    scheme: str = "https",
) -> dict[str, Any]:
    """Build stable SEO/meta output for headless renderers."""
    seo = page_payload.get("seo") if isinstance(page_payload.get("seo"), dict) else {}
    title = str(page_payload.get("title") or "").strip()
    path = str(page_payload.get("path") or "/").strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"

    canonical_url = str(seo.get("canonical_url") or "").strip()
    if not canonical_url and canonical_domain:
        canonical_url = f"{scheme}://{canonical_domain}{path}"

    meta_title = str(seo.get("meta_title") or "").strip() or f"{site.name} | {title}"
    meta_description = (
        str(seo.get("meta_description") or "").strip()
        or site.tagline
        or site.description
        or title
    )
    no_index = bool(seo.get("no_index", False) or (seo.get("robots") or {}).get("no_index", False))
    no_follow = bool(seo.get("no_follow", False) or (seo.get("robots") or {}).get("no_follow", False))

    robots_tokens = []
    robots_tokens.append("noindex" if no_index else "index")
    robots_tokens.append("nofollow" if no_follow else "follow")

    return {
        "title": meta_title,
        "description": meta_description,
        "canonical_url": canonical_url,
        "robots": ",".join(robots_tokens),
        "open_graph": seo.get("og") if isinstance(seo.get("og"), dict) else {},
        "twitter": seo.get("twitter") if isinstance(seo.get("twitter"), dict) else {},
        "structured_data": seo.get("structured_data") if isinstance(seo.get("structured_data"), (dict, list)) else {},
    }


def public_site_capabilities(site: Site) -> dict[str, Any]:
    """Expose runtime capability flags without dashboard/private config."""
    settings = site.settings if isinstance(site.settings, dict) else {}
    features = settings.get("features") if isinstance(settings.get("features"), dict) else {}

    def _feature_enabled(name: str, default: bool = True) -> bool:
        raw = features.get(name)
        if isinstance(raw, dict):
            raw = raw.get("enabled")
        if raw is None:
            legacy = settings.get(name)
            if isinstance(legacy, dict):
                raw = legacy.get("enabled")
        if raw is None:
            return default
        return bool(raw)

    blog_enabled = _feature_enabled("blog", default=True)
    forms_enabled = _feature_enabled("forms", default=True)
    commerce_enabled = _feature_enabled("commerce", default=True)

    return {
        "blog_enabled": blog_enabled,
        "blog_available": blog_enabled
        and site.posts.filter(status=Post.STATUS_PUBLISHED).filter(_is_live_content_q()).exists(),
        "forms_enabled": forms_enabled
        and site.forms.filter(status=Form.STATUS_ACTIVE).exists(),
        "commerce_enabled": commerce_enabled
        and site.products.filter(status=Product.STATUS_PUBLISHED).filter(_is_live_content_q()).exists(),
    }


def public_site_settings(site: Site) -> dict[str, Any]:
    """Return a minimal, explicit settings payload for headless rendering."""
    settings = site.settings if isinstance(site.settings, dict) else {}
    localization = settings.get("localization") if isinstance(settings.get("localization"), dict) else {}
    seo_defaults = settings.get("seo") if isinstance(settings.get("seo"), dict) else {}
    runtime = settings.get("runtime") if isinstance(settings.get("runtime"), dict) else {}
    locales = list(site.locales.filter(is_enabled=True).order_by("-is_default", "code"))
    default_locale = next((locale.code for locale in locales if locale.is_default), "")

    return {
        "theme": site.theme if isinstance(site.theme, dict) else {},
        "localization": {
            "default_locale": localization.get("default_locale") or default_locale or "en",
            "available_locales": [
                {
                    "code": locale.code,
                    "direction": locale.direction,
                    "is_default": locale.is_default,
                }
                for locale in locales
            ],
        },
        "seo_defaults": {
            "meta_title": str(seo_defaults.get("meta_title") or "").strip(),
            "meta_description": str(seo_defaults.get("meta_description") or "").strip(),
            "canonical_url": str(seo_defaults.get("canonical_url") or "").strip(),
            "robots": seo_defaults.get("robots") if isinstance(seo_defaults.get("robots"), dict) else {},
        },
        "runtime": {
            "custom_css_url": str(runtime.get("custom_css_url") or "").strip(),
            "custom_js_url": str(runtime.get("custom_js_url") or "").strip(),
        },
    }


def public_robots_payload(site: Site, sitemap_url: str) -> dict[str, Any]:
    """Return robots payload with custom override support."""
    try:
        robots = site.robots_txt
    except RobotsTxt.DoesNotExist:
        robots = None

    if robots and robots.is_custom:
        content = robots.content
        is_custom = True
    else:
        content = f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n"
        is_custom = False

    return {
        "is_custom": is_custom,
        "sitemap_url": sitemap_url,
        "content": content,
    }


def public_sitemap_entries(site: Site) -> list[dict[str, Any]]:
    """Build sitemap-ready entries for published public content only."""
    pages = (
        site.pages.filter(status=Page.STATUS_PUBLISHED)
        .filter(_is_live_content_q())
        .order_by("-updated_at")
    )
    translations = (
        PageTranslation.objects.select_related("page", "locale")
        .filter(
            page__site=site,
            status=PageTranslation.STATUS_PUBLISHED,
            page__status=Page.STATUS_PUBLISHED,
            locale__is_enabled=True,
        )
        .filter(_is_live_content_q(), _is_live_content_q("page__"))
        .order_by("-updated_at")
    )
    posts = (
        site.posts.filter(status=Post.STATUS_PUBLISHED)
        .filter(_is_live_content_q())
        .order_by("-updated_at")
    )
    products = (
        site.products.filter(status=Product.STATUS_PUBLISHED)
        .filter(_is_live_content_q())
        .order_by("-updated_at")
    )

    entries: list[dict[str, Any]] = []
    for page in pages:
        entries.append(
            {
                "kind": "page",
                "path": page.path if not page.is_homepage else "/",
                "locale": "",
                "last_modified": page.updated_at,
            }
        )
    for translation in translations:
        entries.append(
            {
                "kind": "page_translation",
                "path": translation.path,
                "locale": translation.locale.code,
                "last_modified": translation.updated_at,
            }
        )
    for post in posts:
        entries.append(
            {
                "kind": "blog_post",
                "path": f"/blog/{post.slug}/",
                "locale": "",
                "last_modified": post.updated_at,
            }
        )
    for product in products:
        entries.append(
            {
                "kind": "product",
                "path": f"/shop/{product.slug}/",
                "locale": "",
                "last_modified": product.updated_at,
            }
        )
    return entries


def _clean_runtime_path(path: str | None) -> str:
    value = (path or "").strip()
    if not value:
        return "/"
    parsed = urlparse(value)
    path_value = parsed.path or value
    if not path_value.startswith("/"):
        path_value = f"/{path_value}"
    return "/" if path_value == "/" else f"/{path_value.strip('/')}/"


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in paths:
        normalized = _clean_runtime_path(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def page_revalidation_routes(page: Page, *, include_locale_variants: bool = True) -> list[str]:
    """Compute route paths that should be revalidated for a page change."""
    routes = ["/", page.path]
    if page.is_homepage:
        routes.append("/")

    if include_locale_variants:
        translations = page.translations.select_related("locale").filter(locale__is_enabled=True)
        for translation in translations:
            routes.append(translation.path)
            routes.append(f"/{translation.locale.code}{translation.path}")

    routes.extend(["/sitemap.xml", "/robots.txt"])
    return _dedupe_paths(routes)


def site_revalidation_routes(site: Site, *, include_catalog: bool = True) -> list[str]:
    """Compute site-wide runtime paths for broad invalidation events."""
    routes = ["/", "/sitemap.xml", "/robots.txt"]
    for page in site.pages.filter(status=Page.STATUS_PUBLISHED).only("path", "is_homepage"):
        routes.append("/" if page.is_homepage else page.path)

    translations = (
        PageTranslation.objects.select_related("locale")
        .filter(
            page__site=site,
            status=PageTranslation.STATUS_PUBLISHED,
            page__status=Page.STATUS_PUBLISHED,
            locale__is_enabled=True,
        )
        .filter(_is_live_content_q(), _is_live_content_q("page__"))
        .only("path", "locale__code")
    )
    for translation in translations:
        routes.append(translation.path)
        routes.append(f"/{translation.locale.code}{translation.path}")

    if include_catalog:
        routes.extend(["/blog/", "/shop/"])
    return _dedupe_paths(routes)


def navigation_item_paths(items: list[Any]) -> list[str]:
    """Extract candidate frontend paths from menu item structures."""
    extracted: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("path", "href", "url", "to"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    extracted.append(value.strip())
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(items)
    return _dedupe_paths(extracted)


def enqueue_runtime_revalidation(
    site: Site,
    *,
    event: str,
    paths: list[str] | None = None,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
    priority: int = 10,
):
    """
    Queue an async Next.js runtime revalidation job.

    The queue-backed path gives retries and keeps publish endpoints responsive.
    """
    from jobs.services import create_job

    selected_paths = _dedupe_paths(paths or site_revalidation_routes(site))
    return create_job(
        "runtime_revalidate",
        {
            "site_id": site.id,
            "site_slug": site.slug,
            "event": event,
            "reason": reason,
            "paths": selected_paths,
            "metadata": metadata or {},
        },
        priority=priority,
        idempotency_key=f"runtime_revalidate:{site.id}:{event}:{','.join(selected_paths)}",
        max_retries=5,
    )


def _nextjs_revalidate_url() -> str:
    base = (getattr(settings, "NEXTJS_SITE_RUNTIME_BASE_URL", "") or "").strip().rstrip("/")
    endpoint = (getattr(settings, "NEXTJS_REVALIDATE_ENDPOINT", "") or "/api/revalidate").strip()
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
    return urljoin(f"{base}/", endpoint.lstrip("/")) if base else ""


def dispatch_runtime_revalidation(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Call the Next.js runtime revalidation endpoint securely.

    Raises RuntimeError on transient/failing calls so job workers can retry.
    """
    revalidate_secret = (getattr(settings, "NEXTJS_REVALIDATE_SECRET", "") or "").strip()
    revalidate_url = _nextjs_revalidate_url()
    if not revalidate_url or not revalidate_secret:
        logger.info("Skipping Next.js revalidation; runtime URL/secret not configured.")
        return {"skipped": True, "reason": "not_configured"}

    paths = _dedupe_paths([str(path) for path in payload.get("paths", []) if str(path or "").strip()])
    if not paths:
        return {"skipped": True, "reason": "empty_paths"}

    body = {
        "secret": revalidate_secret,
        "site": payload.get("site_slug", ""),
        "event": payload.get("event", ""),
        "reason": payload.get("reason", ""),
        "paths": paths,
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    raw = json.dumps(body).encode("utf-8")
    timeout_seconds = int(getattr(settings, "NEXTJS_REVALIDATE_TIMEOUT_SECONDS", 10) or 10)
    request = urllib_request.Request(
        revalidate_url,
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Revalidate-Secret": revalidate_secret,
            "User-Agent": "WebsiteBuilder-ISR-Revalidate/1.0",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Revalidation endpoint returned {response.status}: {response_body[:400]}")
            parsed = {}
            if response_body:
                try:
                    parsed = json.loads(response_body)
                except json.JSONDecodeError:
                    parsed = {"raw": response_body[:1000]}
            return {
                "ok": True,
                "status": response.status,
                "paths": paths,
                "response": parsed,
            }
    except urllib_error.HTTPError as exc:
        response_payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {response_payload[:400]}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def process_runtime_revalidation_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Job handler entry point for async runtime cache invalidation."""
    return dispatch_runtime_revalidation(payload)


def publish_page_content(
    page: Page,
    *,
    actor: str = "",
    reason: str = "manual_publish",
    queue_revalidation: bool = True,
) -> dict[str, Any]:
    """
    Publish a page from canonical `builder_data` and queue ISR revalidation.

    Raw HTML/cache fields remain as render artifacts, not source of truth.
    """
    normalized = normalize_page_content(
        title=page.title,
        slug=page.slug,
        path=page.path,
        is_homepage=page.is_homepage,
        status=Page.STATUS_PUBLISHED,
        locale_code="",
        builder_data=page.builder_data,
        seo=page.seo,
        page_settings=page.page_settings,
        html=page.html,
        css=page.css,
        js=page.js,
        schema_version=page.builder_schema_version,
        strict=True,
    )
    page.builder_schema_version = normalized["schema_version"]
    page.builder_data = normalized["builder_data"]
    page.seo = normalized["seo"]
    page.page_settings = normalized["page_settings"]
    page.html = normalized["html"]
    page.css = normalized["css"]
    page.js = normalized["js"]

    sync_homepage_state(page)
    ensure_page_path(page)

    now = timezone.now()
    page.status = Page.STATUS_PUBLISHED
    if page.published_at is None:
        page.published_at = now
    page.scheduled_at = None
    page.save(
        update_fields=[
            "slug",
            "path",
            "status",
            "published_at",
            "scheduled_at",
            "builder_schema_version",
            "builder_data",
            "seo",
            "page_settings",
            "html",
            "css",
            "js",
            "updated_at",
        ]
    )
    create_page_revision(page, "Published snapshot")

    routes = page_revalidation_routes(page)
    job = None
    if queue_revalidation:
        job = enqueue_runtime_revalidation(
            page.site,
            event="page.published",
            paths=routes,
            reason=reason,
            metadata={"page_id": page.id, "path": page.path, "actor": actor},
            priority=20,
        )

    from notifications.services import trigger_webhooks

    trigger_webhooks(
        page.site,
        "page.published",
        {"page_id": page.id, "title": page.title, "path": page.path, "actor": actor},
    )
    return {"page": page, "routes": routes, "job": job}


def unpublish_page_content(
    page: Page,
    *,
    actor: str = "",
    reason: str = "manual_unpublish",
    queue_revalidation: bool = True,
) -> dict[str, Any]:
    """Unpublish a page and invalidate runtime routes that may have cached it."""
    page.status = Page.STATUS_DRAFT
    page.published_at = None
    page.scheduled_at = None
    page.save(update_fields=["status", "published_at", "scheduled_at", "updated_at"])
    create_page_revision(page, "Unpublished snapshot")

    routes = page_revalidation_routes(page)
    job = None
    if queue_revalidation:
        job = enqueue_runtime_revalidation(
            page.site,
            event="page.unpublished",
            paths=routes,
            reason=reason,
            metadata={"page_id": page.id, "path": page.path, "actor": actor},
            priority=20,
        )

    from notifications.services import trigger_webhooks

    trigger_webhooks(
        page.site,
        "page.unpublished",
        {"page_id": page.id, "title": page.title, "path": page.path, "actor": actor},
    )
    return {"page": page, "routes": routes, "job": job}


def schedule_page_publication(page: Page, scheduled_at) -> Any:
    """Persist a page schedule and enqueue background publish processing."""
    from jobs.services import schedule_publish

    if page.status != Page.STATUS_DRAFT:
        raise ValueError("Only draft pages can be scheduled for publication.")
    if scheduled_at is None:
        raise ValueError("scheduled_at is required.")
    if timezone.is_naive(scheduled_at):
        scheduled_at = timezone.make_aware(scheduled_at, timezone.get_current_timezone())
    if scheduled_at <= timezone.now():
        raise ValueError("Scheduled time must be in the future.")

    page.scheduled_at = scheduled_at
    page.save(update_fields=["scheduled_at", "updated_at"])
    return schedule_publish("page", page.id, scheduled_at)


def publish_due_pages(now=None, *, limit: int = 200) -> dict[str, Any]:
    """Publish due scheduled pages and enqueue runtime revalidation jobs."""
    current_time = now or timezone.now()
    due_pages = (
        Page.objects.select_related("site")
        .filter(status=Page.STATUS_DRAFT, scheduled_at__isnull=False, scheduled_at__lte=current_time)
        .order_by("scheduled_at")[:limit]
    )
    published = 0
    page_ids: list[int] = []
    for page in due_pages:
        publish_page_content(page, actor="scheduler", reason="scheduled_publish")
        published += 1
        page_ids.append(page.id)
    return {"published_count": published, "page_ids": page_ids}


def enqueue_site_revalidation(
    site: Site,
    *,
    event: str,
    reason: str = "",
    extra_paths: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Queue a broad site runtime revalidation event."""
    all_paths = site_revalidation_routes(site)
    if extra_paths:
        all_paths.extend(extra_paths)
    return enqueue_runtime_revalidation(
        site,
        event=event,
        paths=_dedupe_paths(all_paths),
        reason=reason,
        metadata=metadata,
        priority=10,
    )


def enqueue_navigation_revalidation(menu: Any, *, reason: str = "navigation_changed"):
    """Queue route invalidation for navigation/menu updates."""
    menu_paths = navigation_item_paths(menu.items if hasattr(menu, "items") else [])
    menu_paths.extend(["/", "/sitemap.xml"])
    return enqueue_runtime_revalidation(
        menu.site,
        event="site.navigation.changed",
        paths=_dedupe_paths(menu_paths),
        reason=reason,
        metadata={"menu_id": getattr(menu, "id", None), "menu_slug": getattr(menu, "slug", "")},
        priority=10,
    )


def ensure_page_path(page: Any) -> None:
    """Ensure ``page.path`` is unique for its site."""
    builder_services.ensure_unique_page_path(page)


def apply_page_payload(page: Any, payload: dict[str, Any]) -> None:
    """Apply builder payload fields onto a page instance."""
    builder_services.build_page_payload(page, payload)


def create_page_revision(page: Any, label: str):
    """Create a point-in-time revision for the page."""
    return builder_services.create_revision(page, label)


__all__ = [
    "BASE_BLOCK_CSS",
    "PAGE_SCHEMA_VERSION",
    "apply_page_payload",
    "build_public_meta_payload",
    "build_public_page_payload",
    "create_page_revision",
    "ensure_global_block_templates",
    "ensure_page_path",
    "ensure_site_cms_modules",
    "extract_page_summary",
    "extract_render_cache",
    "normalize_page_content",
    "normalize_page_path",
    "normalize_runtime_page_path",
    "navigation_item_paths",
    "dispatch_runtime_revalidation",
    "enqueue_navigation_revalidation",
    "enqueue_runtime_revalidation",
    "enqueue_site_revalidation",
    "public_robots_payload",
    "public_site_capabilities",
    "public_site_settings",
    "public_sitemap_entries",
    "page_revalidation_routes",
    "process_runtime_revalidation_job",
    "publish_due_pages",
    "publish_page_content",
    "preview_url_for_page",
    "preview_url_for_page_translation",
    "PublicPageResolution",
    "resolve_public_locale",
    "resolve_public_page",
    "schedule_page_publication",
    "section_component_registry",
    "site_revalidation_routes",
    "sync_homepage_state",
    "unpublish_page_content",
]
