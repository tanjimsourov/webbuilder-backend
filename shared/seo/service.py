from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_bool(value: Any) -> bool:
    return bool(value is True or str(value).strip().lower() in {"1", "true", "yes", "on"})


def normalize_seo_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = _as_dict(payload)
    robots = _as_dict(source.get("robots"))
    no_index = _as_bool(source.get("no_index")) or _as_bool(robots.get("no_index")) or _as_bool(robots.get("noindex"))
    no_follow = _as_bool(source.get("no_follow")) or _as_bool(robots.get("no_follow")) or _as_bool(robots.get("nofollow"))
    structured_data = source.get("structured_data")
    if not isinstance(structured_data, (dict, list)):
        structured_data = {}
    return {
        "meta_title": str(source.get("meta_title") or "").strip()[:280],
        "meta_description": str(source.get("meta_description") or "").strip()[:500],
        "canonical_url": str(source.get("canonical_url") or "").strip()[:1000],
        "open_graph": _as_dict(source.get("open_graph") or source.get("og")),
        "twitter": _as_dict(source.get("twitter")),
        "structured_data": structured_data,
        "robots": {
            "no_index": no_index,
            "no_follow": no_follow,
        },
        "no_index": no_index,
        "no_follow": no_follow,
    }


def build_seo_payload(
    *,
    title: str,
    description: str = "",
    canonical_url: str = "",
    payload: dict[str, Any] | None = None,
    default_title_prefix: str = "",
) -> dict[str, Any]:
    normalized = normalize_seo_payload(payload)
    fallback_title = f"{default_title_prefix}{title}".strip()
    final_title = normalized["meta_title"] or fallback_title
    final_description = normalized["meta_description"] or description or title
    open_graph = _as_dict(normalized.get("open_graph"))
    if not open_graph.get("title"):
        open_graph["title"] = final_title
    if not open_graph.get("description"):
        open_graph["description"] = final_description
    if canonical_url and not normalized["canonical_url"]:
        normalized["canonical_url"] = canonical_url
    normalized["meta_title"] = final_title
    normalized["meta_description"] = final_description
    normalized["open_graph"] = open_graph
    return normalized
