"""
Platform app registry and hook surface.

This is the first step toward a real extension SDK. It uses Pluggy when
available, and falls back to a small in-process hook runner so the platform
still works in local environments before optional dependencies are installed.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from collections.abc import Iterable
from typing import Any

from django.utils.html import strip_tags

from .librecrawl_service import librecrawl_installed
from .payload_service import payload_cms_source_exists, payload_ecommerce_source_exists
from .search_services import search_service
from .serpbear_service import serpbear_source_exists
from .umami_service import umami_source_exists

logger = logging.getLogger(__name__)

PROJECT_NAME = "smc_web_builder"

try:
    import pluggy  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pluggy = None


def _passthrough_marker(func=None, **_kwargs):
    if callable(func):
        return func

    def decorator(inner):
        return inner

    return decorator


hookspec = pluggy.HookspecMarker(PROJECT_NAME) if pluggy else _passthrough_marker
hookimpl = pluggy.HookimplMarker(PROJECT_NAME) if pluggy else _passthrough_marker


def _package_available(package_name: str) -> bool:
    return importlib.util.find_spec(package_name) is not None


class BuilderHookSpecs:
    @hookspec
    def platform_apps(self) -> list[dict[str, Any]]:
        """Return platform app manifests."""

    @hookspec
    def ai_prompt_context(self, goal: str, site, page, payload: dict[str, Any]) -> dict[str, Any]:
        """Return additional context for an AI generation request."""

    @hookspec
    def ai_postprocess(self, goal: str, site, page, suggestion: dict[str, Any]) -> dict[str, Any]:
        """Normalize or enrich AI output."""


class _FallbackHookProxy:
    def __init__(self, plugins: list[object]):
        self._plugins = plugins

    def _call(self, method_name: str, *args, **kwargs) -> list[Any]:
        results: list[Any] = []
        for plugin in self._plugins:
            method = getattr(plugin, method_name, None)
            if callable(method):
                results.append(method(*args, **kwargs))
        return results

    def platform_apps(self) -> list[Any]:
        return self._call("platform_apps")

    def ai_prompt_context(self, **kwargs) -> list[Any]:
        return self._call("ai_prompt_context", **kwargs)

    def ai_postprocess(self, **kwargs) -> list[Any]:
        return self._call("ai_postprocess", **kwargs)


class PlatformAppRegistry:
    def __init__(self):
        self._plugins: list[object] = []
        self._manager = pluggy.PluginManager(PROJECT_NAME) if pluggy else None
        if self._manager:
            self._manager.add_hookspecs(BuilderHookSpecs)

    @property
    def hook(self):
        if self._manager:
            return self._manager.hook
        return _FallbackHookProxy(self._plugins)

    def register(self, plugin: object, name: str | None = None):
        if self._manager:
            self._manager.register(plugin, name=name)
        else:
            self._plugins.append(plugin)

    def list_apps(self) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        for contribution in self.hook.platform_apps():
            if isinstance(contribution, dict):
                manifests.append(contribution)
            elif isinstance(contribution, Iterable):
                manifests.extend(item for item in contribution if isinstance(item, dict))
        return sorted(
            manifests,
            key=lambda item: (
                str(item.get("category", "")),
                str(item.get("name", "")),
            ),
        )

    def build_ai_context(self, goal: str, site, page, payload: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for contribution in self.hook.ai_prompt_context(goal=goal, site=site, page=page, payload=payload):
            if isinstance(contribution, dict):
                for key, value in contribution.items():
                    if value not in (None, "", [], {}):
                        merged[key] = value
        return merged

    def postprocess_ai_output(self, goal: str, site, page, suggestion: dict[str, Any]) -> dict[str, Any]:
        current = dict(suggestion)
        for contribution in self.hook.ai_postprocess(goal=goal, site=site, page=page, suggestion=current):
            if isinstance(contribution, dict):
                current.update({key: value for key, value in contribution.items() if value not in (None, "", [])})
        return current


def _trim_text(value: str, limit: int) -> str:
    compact = " ".join(strip_tags(value or "").split())
    if len(compact) <= limit:
        return compact
    shortened = compact[: limit - 1].rstrip(" ,;:-")
    return f"{shortened}..."


def _normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, Iterable):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []

    seen: set[str] = set()
    keywords: list[str] = []
    for item in raw_items:
        cleaned = " ".join(item.strip().split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        keywords.append(cleaned)
    return keywords[:8]


class CorePlatformPlugin:
    @hookimpl
    def platform_apps(self) -> list[dict[str, Any]]:
        openai_ready = bool(os.environ.get("OPENAI_API_KEY")) and _package_available("openai")
        pluggy_ready = pluggy is not None

        return [
            {
                "id": "editor.grapesjs",
                "name": "GrapesJS Visual Builder",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Drag-and-drop page building with reusable blocks and responsive editing.",
                "source_url": "https://github.com/GrapesJS/grapesjs",
                "capabilities": ["visual-editing", "responsive-preview", "block-library"],
                "is_configured": True,
            },
            {
                "id": "editor.grapesjs-preset-webpage",
                "name": "GrapesJS Webpage Preset",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Production-ready page blocks, default sections, and responsive starter structures for the visual builder.",
                "source_url": "https://www.npmjs.com/package/grapesjs-preset-webpage",
                "capabilities": ["starter-layouts", "section-blocks", "responsive-presets"],
                "is_configured": True,
            },
            {
                "id": "editor.grapesjs-plugin-forms",
                "name": "GrapesJS Forms Plugin",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Visual form controls for lead capture, checkout forms, and operational workflows inside the page builder.",
                "source_url": "https://www.npmjs.com/package/grapesjs-plugin-forms",
                "capabilities": ["form-blocks", "input-controls", "lead-capture"],
                "is_configured": True,
            },
            {
                "id": "editor.grapesjs-navbar",
                "name": "GrapesJS Navbar Plugin",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Navigation block tooling for responsive headers, menus, and multi-level site navigation patterns.",
                "source_url": "https://www.npmjs.com/package/grapesjs-navbar",
                "capabilities": ["navigation-blocks", "responsive-menus", "header-builder"],
                "is_configured": True,
            },
            {
                "id": "editor.grapesjs-tui-image-editor",
                "name": "TUI Image Editor",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Inline image editing stack for cropping, filters, annotations, and asset preparation directly in the builder.",
                "source_url": "https://www.npmjs.com/package/grapesjs-tui-image-editor",
                "capabilities": ["image-editing", "crop-and-annotate", "asset-prep"],
                "is_configured": True,
            },
            {
                "id": "cms.payload",
                "name": "Payload Website CMS",
                "category": "cms",
                "status": "active" if payload_cms_source_exists() else "available",
                "provider": "oss",
                "description": "Next.js-native headless CMS template with drafts, layout blocks, live preview, redirects, and content workflows.",
                "source_url": "https://github.com/payloadcms/payload/tree/main/templates/website",
                "capabilities": ["headless-cms", "draft-preview", "layout-builder", "redirects"],
                "is_configured": payload_cms_source_exists(),
            },
            {
                "id": "commerce.payload-ecommerce",
                "name": "Payload Ecommerce Template",
                "category": "commerce",
                "status": "active" if payload_ecommerce_source_exists() else "available",
                "provider": "oss",
                "description": "Production ecommerce starter with products, carts, orders, guest checkout, Stripe, and a full admin surface.",
                "source_url": "https://github.com/payloadcms/payload/tree/main/templates/ecommerce",
                "capabilities": ["catalog", "checkout", "orders", "stripe"],
                "is_configured": payload_ecommerce_source_exists(),
            },
            {
                "id": "search.meilisearch",
                "name": "Meilisearch Workspace Search",
                "category": "search",
                "status": "active" if search_service.enabled else "available",
                "provider": "oss",
                "description": "Instant workspace search across pages, posts, products, and media.",
                "source_url": "https://github.com/meilisearch/meilisearch",
                "capabilities": ["instant-search", "cross-content-search", "operator-search"],
                "is_configured": search_service.enabled,
            },
            {
                "id": "analytics.umami",
                "name": "Umami Product Analytics",
                "category": "analytics",
                "status": "active" if umami_source_exists() else "available",
                "provider": "oss",
                "description": "Privacy-first web analytics companion for site traffic, attribution, and event reporting.",
                "source_url": "https://github.com/umami-software/umami",
                "capabilities": ["traffic-analytics", "event-tracking", "privacy-first"],
                "is_configured": umami_source_exists(),
            },
            {
                "id": "seo.librecrawl",
                "name": "LibreCrawl Technical SEO",
                "category": "seo",
                "status": "active" if librecrawl_installed() else "available",
                "provider": "oss",
                "description": "Full-site crawl, issue detection, exports, and technical SEO diagnostics.",
                "source_url": "https://github.com/PhialsBasement/LibreCrawl",
                "capabilities": ["site-crawl", "issue-detection", "pagespeed", "exports"],
                "is_configured": librecrawl_installed(),
            },
            {
                "id": "seo.serpbear",
                "name": "SerpBear Rank Tracker",
                "category": "seo",
                "status": "active" if serpbear_source_exists() else "available",
                "provider": "oss",
                "description": "Keyword rank tracking, keyword research, and Google Search Console-assisted SEO workflows.",
                "source_url": "https://github.com/towfiqi/serpbear",
                "capabilities": ["rank-tracking", "keyword-research", "gsc-insights"],
                "is_configured": serpbear_source_exists(),
            },
            {
                "id": "planner.xyflow",
                "name": "XYFlow Visual Sitemap",
                "category": "editor",
                "status": "active",
                "provider": "oss",
                "description": "Interactive site-map planning canvas for AI-generated page trees and information architecture.",
                "source_url": "https://github.com/xyflow/xyflow",
                "capabilities": ["visual-sitemap", "page-planning", "node-graph-ui"],
                "is_configured": True,
            },
            {
                "id": "experiments.growthbook",
                "name": "GrowthBook Experiments",
                "category": "experimentation",
                "status": "active",
                "provider": "oss",
                "description": "Experiment delivery patterns for page tests, rollout control, and future feature flags.",
                "source_url": "https://github.com/growthbook/growthbook",
                "capabilities": ["a-b-testing", "feature-flags", "targeting"],
                "is_configured": True,
            },
            {
                "id": "forms.react-hook-form",
                "name": "React Hook Form Builder",
                "category": "forms",
                "status": "active",
                "provider": "oss",
                "description": "Fast form state and validation patterns for advanced public forms and editor workflows.",
                "source_url": "https://github.com/react-hook-form/react-hook-form",
                "capabilities": ["form-state", "validation", "performance"],
                "is_configured": True,
            },
            {
                "id": "collab.react-mentions",
                "name": "React Mentions Collaboration",
                "category": "collaboration",
                "status": "active",
                "provider": "oss",
                "description": "Mention-aware commenting for review flows, editorial feedback, and team collaboration.",
                "source_url": "https://github.com/signavio/react-mentions",
                "capabilities": ["mentions", "review-comments", "team-collaboration"],
                "is_configured": True,
            },
            {
                "id": "sdk.pluggy",
                "name": "Pluggy App SDK",
                "category": "platform",
                "status": "active" if pluggy_ready else "degraded",
                "provider": "oss",
                "description": "Hook-based foundation for future apps, extensions, and marketplace installs.",
                "source_url": "https://github.com/pytest-dev/pluggy",
                "capabilities": ["hook-registry", "app-discovery", "sdk-foundation"],
                "is_configured": pluggy_ready,
            },
            {
                "id": "ai.studio",
                "name": "AI Studio",
                "category": "ai",
                "status": "active" if openai_ready else "fallback",
                "provider": "hybrid",
                "description": "Minimal copy and SEO suggestions with OpenAI when configured and deterministic fallback otherwise.",
                "source_url": "https://github.com/openai/openai-python",
                "capabilities": ["hero-copy", "seo-suggestions", "metadata-drafting"],
                "is_configured": openai_ready,
            },
        ]

    @hookimpl
    def ai_prompt_context(self, goal: str, site, page, payload: dict[str, Any]) -> dict[str, Any]:
        page_seo = getattr(page, "seo", {}) or {}
        site_description = getattr(site, "description", "") or getattr(site, "tagline", "")
        page_html = getattr(page, "html", "") or ""
        existing_pages = []
        if hasattr(site, "pages"):
            existing_pages = [
                {
                    "title": item.title,
                    "slug": item.slug,
                    "path": item.path,
                    "is_homepage": item.is_homepage,
                    "status": item.status,
                }
                for item in site.pages.order_by("-is_homepage", "title")[:20]
            ]

        return {
            "goal": goal,
            "site_name": getattr(site, "name", ""),
            "site_tagline": getattr(site, "tagline", ""),
            "site_description": site_description,
            "site_domain": getattr(site, "domain", ""),
            "site_navigation": getattr(site, "navigation", []) or [],
            "page_title": getattr(page, "title", ""),
            "page_path": getattr(page, "path", ""),
            "page_slug": getattr(page, "slug", ""),
            "page_meta_title": page_seo.get("meta_title", ""),
            "page_meta_description": page_seo.get("meta_description", ""),
            "page_excerpt": _trim_text(page_html, 320),
            "brief": _trim_text(str(payload.get("brief", "")), 360),
            "audience": _trim_text(str(payload.get("audience", "")), 180),
            "offering": _trim_text(str(payload.get("offering", "")), 180),
            "tone": _trim_text(str(payload.get("tone", "")), 80),
            "keywords": _normalize_keywords(payload.get("keywords", [])),
            "existing_pages": existing_pages,
            "has_blog": bool(getattr(site, "posts", None) and site.posts.exists()),
            "has_store": bool(getattr(site, "products", None) and site.products.exists()),
        }

    @hookimpl
    def ai_postprocess(self, goal: str, site, page, suggestion: dict[str, Any]) -> dict[str, Any]:
        site_name = getattr(site, "name", "")
        title = suggestion.get("title") or getattr(page, "title", "") or getattr(site, "name", "")
        hero_heading = suggestion.get("hero_heading") or title
        hero_subheading = suggestion.get("hero_subheading") or getattr(site, "tagline", "") or getattr(site, "description", "")
        cta_label = suggestion.get("cta_label") or "Get started"
        meta_title = suggestion.get("meta_title") or title
        if site_name and site_name.lower() not in meta_title.lower():
            meta_title = f"{meta_title} | {site_name}"
        meta_description = suggestion.get("meta_description") or hero_subheading or getattr(site, "description", "")
        normalized = {
            "title": _trim_text(str(title), 65),
            "hero_heading": _trim_text(str(hero_heading), 72),
            "hero_subheading": _trim_text(str(hero_subheading), 170),
            "cta_label": _trim_text(str(cta_label), 28),
            "meta_title": _trim_text(str(meta_title), 60),
            "meta_description": _trim_text(str(meta_description), 155),
            "focus_keywords": _normalize_keywords(suggestion.get("focus_keywords") or suggestion.get("keywords") or []),
        }
        if goal == "page_seo":
            normalized["hero_heading"] = normalized["title"]
        return normalized


platform_app_registry = PlatformAppRegistry()
platform_app_registry.register(CorePlatformPlugin(), name="core-platform")
