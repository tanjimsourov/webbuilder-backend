"""Analytics domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import seo_services


def run_seo_page_audit(page: Any, base_url: str):
    """Run an SEO audit for a single page."""
    return seo_services.run_page_audit(page, base_url)


def sync_search_console(site: Any, days: int = 90):
    """Fetch and persist Google Search Console metrics."""
    return seo_services.gsc_sync(site, days=days)


def disconnect_search_console(site: Any) -> None:
    """Disconnect Google Search Console for a site."""
    seo_services.gsc_disconnect(site)


def list_search_console_properties(site: Any) -> list[str]:
    """Return GSC properties available to the connected account."""
    return seo_services.gsc_list_properties(site)


__all__ = [
    "disconnect_search_console",
    "list_search_console_properties",
    "run_seo_page_audit",
    "sync_search_console",
]
