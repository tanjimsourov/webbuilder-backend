"""Blog domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import services as builder_services


def post_preview_url(post: Any) -> str:
    """Return the preview URL for a blog post."""
    return builder_services.preview_url_for_post(post)


__all__ = [
    "post_preview_url",
]
