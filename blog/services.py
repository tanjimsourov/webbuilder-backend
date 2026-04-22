"""Blog domain service wrappers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from builder import services as builder_services
from shared.seo import build_seo_payload


def post_preview_url(post: Any) -> str:
    """Return the preview URL for a blog post."""
    return builder_services.preview_url_for_post(post)


@dataclass(frozen=True)
class SpamCheckResult:
    is_spam: bool
    score: float
    provider: str
    notes: str = ""


def evaluate_comment_spam(*, author_email: str, body: str) -> SpamCheckResult:
    """
    Pluggable spam-evaluation hook.

    Default behavior is heuristic-only and intentionally conservative.
    """
    provider = os.environ.get("BLOG_SPAM_PROVIDER", "heuristic").strip().lower() or "heuristic"
    content = f"{author_email} {body}".lower()
    score = 0.0
    spam_tokens = ["http://", "https://", "viagra", "casino", "crypto giveaway", "buy now"]
    for token in spam_tokens:
        if token in content:
            score += 0.2
    score = min(1.0, score)
    is_spam = score >= float(os.environ.get("BLOG_SPAM_THRESHOLD", "0.7") or "0.7")
    return SpamCheckResult(is_spam=is_spam, score=score, provider=provider)


def post_seo_payload(post: Any, *, canonical_domain: str = "", scheme: str = "https") -> dict[str, Any]:
    canonical_url = f"{scheme}://{canonical_domain}/blog/{post.slug}/" if canonical_domain else ""
    return build_seo_payload(
        title=post.title,
        description=post.excerpt or post.title,
        canonical_url=canonical_url,
        payload=post.seo if isinstance(post.seo, dict) else {},
        default_title_prefix=f"{post.site.name} | ",
    )


__all__ = [
    "SpamCheckResult",
    "evaluate_comment_spam",
    "post_seo_payload",
    "post_preview_url",
]
