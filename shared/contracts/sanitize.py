from __future__ import annotations

import re
from typing import Any

from django.utils.html import strip_tags


_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_RICH_ALLOWED_TAGS = [
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "ul",
]
_RICH_ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height", "loading"],
    "span": ["class"],
    "p": ["class"],
    "code": ["class"],
}


def sanitize_text(value: str, *, max_length: int | None = None) -> str:
    cleaned = strip_tags(value or "")
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    if max_length is not None:
        return cleaned[:max_length]
    return cleaned


def sanitize_rich_html(value: str, *, max_length: int | None = None) -> str:
    raw = _CONTROL_RE.sub("", value or "")
    try:
        import bleach

        cleaned = bleach.clean(
            raw,
            tags=_RICH_ALLOWED_TAGS,
            attributes=_RICH_ALLOWED_ATTRS,
            protocols=["http", "https", "mailto"],
            strip=True,
            strip_comments=True,
        )
    except Exception:
        cleaned = strip_tags(raw)
    if max_length is not None:
        return cleaned[:max_length]
    return cleaned


def sanitize_json_payload(value: Any, *, max_depth: int = 4) -> Any:
    if max_depth < 0:
        return None
    if isinstance(value, dict):
        return {sanitize_text(str(k), max_length=120): sanitize_json_payload(v, max_depth=max_depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json_payload(item, max_depth=max_depth - 1) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, max_length=4000)
    return value
