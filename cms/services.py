"""CMS domain service wrappers.

This module is the app-level home for page and media business logic.
Current implementations call into legacy ``builder.services`` while the
monolith is being split by domain.
"""

from __future__ import annotations

from typing import Any

from builder import services as builder_services

BASE_BLOCK_CSS = builder_services.BASE_BLOCK_CSS
ensure_global_block_templates = builder_services.ensure_global_block_templates
ensure_site_cms_modules = builder_services.ensure_site_cms_modules
normalize_page_path = builder_services.normalize_page_path
preview_url_for_page = builder_services.preview_url_for_page
preview_url_for_page_translation = builder_services.preview_url_for_page_translation
sync_homepage_state = builder_services.sync_homepage_state


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
    "apply_page_payload",
    "create_page_revision",
    "ensure_global_block_templates",
    "ensure_page_path",
    "ensure_site_cms_modules",
    "normalize_page_path",
    "preview_url_for_page",
    "preview_url_for_page_translation",
    "sync_homepage_state",
]
