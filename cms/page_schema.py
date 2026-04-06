from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.utils.text import slugify


PAGE_SCHEMA_VERSION = 2
SUPPORTED_PAGE_SCHEMA_VERSIONS = {1, PAGE_SCHEMA_VERSION}
SECTION_CONTRACT_VERSION = 1

SECTION_COMPONENT_REGISTRY: dict[str, dict[str, Any]] = {
    "core.hero": {"label": "Hero", "category": "hero", "data_sources": ["static"]},
    "core.feature-grid": {"label": "Feature Grid", "category": "feature", "data_sources": ["static"]},
    "core.cta": {"label": "Call To Action", "category": "cta", "data_sources": ["static"]},
    "core.testimonials": {"label": "Testimonials", "category": "testimonial", "data_sources": ["static"]},
    "core.pricing": {"label": "Pricing", "category": "pricing", "data_sources": ["static"]},
    "core.faq": {"label": "FAQ", "category": "faq", "data_sources": ["static"]},
    "core.footer": {"label": "Footer", "category": "footer", "data_sources": ["static"]},
    "core.header": {"label": "Header", "category": "header", "data_sources": ["static"]},
    "core.rich-text": {"label": "Rich Text", "category": "content", "data_sources": ["static"]},
    "core.gallery": {"label": "Gallery", "category": "gallery", "data_sources": ["static"]},
    "core.stats": {"label": "Stats", "category": "content", "data_sources": ["static"]},
    "core.timeline": {"label": "Timeline", "category": "content", "data_sources": ["static"]},
    "core.video": {"label": "Video", "category": "content", "data_sources": ["static"]},
    "forms.form-embed": {"label": "Form Embed", "category": "form", "data_sources": ["forms.form", "static"]},
    "blog.post-list": {"label": "Blog Post List", "category": "content", "data_sources": ["blog.posts", "static"]},
    "blog.post-detail": {"label": "Blog Post Detail", "category": "content", "data_sources": ["blog.post", "static"]},
    "blog.category-list": {"label": "Blog Category List", "category": "content", "data_sources": ["blog.posts", "static"]},
    "commerce.product-list": {"label": "Product List", "category": "content", "data_sources": ["commerce.products", "static"]},
    "commerce.product-detail": {"label": "Product Detail", "category": "content", "data_sources": ["commerce.product", "static"]},
    "commerce.category-grid": {"label": "Category Grid", "category": "content", "data_sources": ["commerce.categories", "static"]},
    "commerce.cart-summary": {"label": "Cart Summary", "category": "content", "data_sources": ["commerce.products", "static"]},
    "navigation.menu": {"label": "Navigation Menu", "category": "header", "data_sources": ["navigation.menu", "static"]},
}
SUPPORTED_SECTION_COMPONENT_KEYS = set(SECTION_COMPONENT_REGISTRY.keys())

SECTION_COMPONENT_ALIASES = {
    "hero": "core.hero",
    "feature": "core.feature-grid",
    "features": "core.feature-grid",
    "cta": "core.cta",
    "testimonial": "core.testimonials",
    "testimonials": "core.testimonials",
    "pricing": "core.pricing",
    "faq": "core.faq",
    "footer": "core.footer",
    "header": "core.header",
    "content": "core.rich-text",
    "text": "core.rich-text",
    "richtext": "core.rich-text",
    "gallery": "core.gallery",
    "stats": "core.stats",
    "timeline": "core.timeline",
    "video": "core.video",
    "form": "forms.form-embed",
    "forms": "forms.form-embed",
    "blog": "blog.post-list",
    "blog.posts": "blog.post-list",
    "blog-posts": "blog.post-list",
    "products": "commerce.product-list",
    "product": "commerce.product-detail",
    "shop": "commerce.product-list",
    "commerce.products": "commerce.product-list",
    "commerce.product": "commerce.product-detail",
    "commerce.categories": "commerce.category-grid",
    "menu": "navigation.menu",
    "navigation": "navigation.menu",
}

BLOCK_TEMPLATE_CATEGORY_DEFAULT_COMPONENTS = {
    "hero": "core.hero",
    "feature": "core.feature-grid",
    "cta": "core.cta",
    "testimonial": "core.testimonials",
    "pricing": "core.pricing",
    "faq": "core.faq",
    "footer": "core.footer",
    "header": "navigation.menu",
    "content": "core.rich-text",
    "gallery": "core.gallery",
    "form": "forms.form-embed",
    "other": "core.rich-text",
}

SUPPORTED_SECTION_DATA_SOURCE_TYPES = {
    "none",
    "static",
    "forms.form",
    "blog.posts",
    "blog.post",
    "commerce.products",
    "commerce.product",
    "commerce.categories",
    "navigation.menu",
    "site.settings",
}

_SECTION_DATA_SOURCE_ALIASES = {
    "none": "none",
    "static": "static",
    "form": "forms.form",
    "forms": "forms.form",
    "forms.form": "forms.form",
    "blog": "blog.posts",
    "blog.posts": "blog.posts",
    "blog.post": "blog.post",
    "posts": "blog.posts",
    "products": "commerce.products",
    "product": "commerce.product",
    "categories": "commerce.categories",
    "commerce.products": "commerce.products",
    "commerce.product": "commerce.product",
    "commerce.categories": "commerce.categories",
    "menu": "navigation.menu",
    "navigation.menu": "navigation.menu",
    "site": "site.settings",
    "site.settings": "site.settings",
}

_COMPONENT_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
_CANONICAL_SCHEMA_KEYS = {
    "schema_version",
    "metadata",
    "route",
    "seo",
    "layout",
    "style_tokens",
    "section_contract",
    "sections",
    "locales",
    "render_cache",
    "legacy",
}


def _validation_error(field: str, message: str) -> ValidationError:
    return ValidationError({field: message})


def _as_dict(field: str, value: Any, *, strict: bool) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return deepcopy(value)
    if strict:
        raise _validation_error(field, "Must be a JSON object.")
    return {}


def _as_list(field: str, value: Any, *, strict: bool) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return deepcopy(value)
    if strict:
        raise _validation_error(field, "Must be a JSON array.")
    return []


def _as_int(field: str, value: Any, *, default: int, minimum: int = 0, strict: bool) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise _validation_error(field, "Must be an integer.") from exc
        return default
    if parsed < minimum:
        if strict:
            raise _validation_error(field, f"Must be greater than or equal to {minimum}.")
        return default
    return parsed


def normalize_route_path(path: str | None, *, is_homepage: bool, slug: str) -> str:
    if is_homepage:
        return "/"

    raw_path = (path or "").strip()
    if raw_path and raw_path != "/":
        clean_path = raw_path.strip("/")
        if clean_path:
            return f"/{clean_path}/"

    clean_slug = slugify(slug or "") or "page"
    return f"/{clean_slug}/"


def _normalize_schema_version(value: Any, *, strict: bool) -> int:
    if value in (None, ""):
        return PAGE_SCHEMA_VERSION

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        if strict:
            raise _validation_error("builder_schema_version", "Must be an integer.") from exc
        return PAGE_SCHEMA_VERSION

    if parsed <= 0:
        if strict:
            raise _validation_error("builder_schema_version", "Must be greater than zero.")
        return PAGE_SCHEMA_VERSION

    if parsed not in SUPPORTED_PAGE_SCHEMA_VERSIONS:
        if strict:
            supported = ", ".join(str(item) for item in sorted(SUPPORTED_PAGE_SCHEMA_VERSIONS))
            raise _validation_error(
                "builder_schema_version",
                f"Unsupported schema version {parsed}. Supported versions: {supported}.",
            )
        return PAGE_SCHEMA_VERSION

    # Always persist the latest contract version after normalization.
    if parsed < PAGE_SCHEMA_VERSION:
        return PAGE_SCHEMA_VERSION
    return parsed


def _normalize_seo(raw: Any, *, strict: bool) -> dict[str, Any]:
    data = _as_dict("seo", raw, strict=strict)
    keywords = data.get("focus_keywords") or data.get("meta_keywords") or []
    if not isinstance(keywords, list):
        if strict:
            raise _validation_error("seo.focus_keywords", "Must be a list of strings.")
        keywords = []

    normalized_keywords = []
    for keyword in keywords:
        text = str(keyword or "").strip()
        if text:
            normalized_keywords.append(text)

    robots = data.get("robots")
    if robots is None:
        robots_data: dict[str, Any] = {}
    elif isinstance(robots, dict):
        robots_data = dict(robots)
    else:
        if strict:
            raise _validation_error("seo.robots", "Must be a JSON object.")
        robots_data = {}

    return {
        "meta_title": str(data.get("meta_title") or "").strip(),
        "meta_description": str(data.get("meta_description") or "").strip(),
        "canonical_url": str(data.get("canonical_url") or "").strip(),
        "focus_keywords": normalized_keywords,
        "no_index": bool(data.get("no_index", False)),
        "no_follow": bool(data.get("no_follow", False)),
        "robots": {
            "no_index": bool(robots_data.get("no_index", data.get("no_index", False))),
            "no_follow": bool(robots_data.get("no_follow", data.get("no_follow", False))),
        },
        "og": _as_dict("seo.og", data.get("og"), strict=False),
        "twitter": _as_dict("seo.twitter", data.get("twitter"), strict=False),
        "structured_data": deepcopy(data.get("structured_data", {})),
    }


def _sanitize_component_key(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    value = value.replace("/", ".")
    value = value.replace(" ", "-")
    value = re.sub(r"[^a-z0-9._-]+", "", value)
    return value.strip(".-_")


def _normalize_component_key(
    raw_component: Any,
    fallback_type: Any,
    *,
    strict: bool,
    field: str,
) -> str:
    candidate = _sanitize_component_key(raw_component)
    if not candidate:
        candidate = _sanitize_component_key(fallback_type)

    if candidate in SECTION_COMPONENT_ALIASES:
        candidate = SECTION_COMPONENT_ALIASES[candidate]
    if candidate in SUPPORTED_SECTION_COMPONENT_KEYS:
        return candidate

    if not candidate:
        if strict:
            raise _validation_error(field, "Each section requires a valid component key.")
        return "core.rich-text"

    if _COMPONENT_KEY_RE.fullmatch(candidate) and candidate.startswith("custom."):
        return candidate

    if strict:
        supported_keys = ", ".join(sorted(SUPPORTED_SECTION_COMPONENT_KEYS))
        raise _validation_error(
            field,
            f"Unsupported component key '{candidate}'. Supported keys: {supported_keys}.",
        )

    slug_value = slugify(candidate).replace("-", ".").strip(".")
    if not slug_value:
        return "core.rich-text"
    return f"custom.{slug_value}"


def normalize_component_key(value: Any, *, strict: bool = True, field: str = "component") -> str:
    """Normalize and validate a section/component key used by the runtime registry."""
    return _normalize_component_key(value, "", strict=strict, field=field)


def default_renderer_key_for_block_category(category: str | None) -> str:
    """Return the canonical runtime component key for a block category."""
    normalized = str(category or "").strip().lower()
    return BLOCK_TEMPLATE_CATEGORY_DEFAULT_COMPONENTS.get(normalized, "core.rich-text")


def normalize_block_template_renderer_key(
    renderer_key: Any,
    *,
    category: str | None = None,
    strict: bool = True,
) -> str:
    """
    Normalize block template renderer keys to the same component namespace
    used by page sections.
    """
    fallback = default_renderer_key_for_block_category(category)
    value = renderer_key if str(renderer_key or "").strip() else fallback
    return _normalize_component_key(value, fallback, strict=strict, field="renderer_key")


def _normalize_visibility(raw: Any, location: str, *, strict: bool) -> dict[str, Any]:
    if raw is None:
        return {"enabled": True, "audience": [], "rules": []}
    if isinstance(raw, bool):
        return {"enabled": bool(raw), "audience": [], "rules": []}

    data = _as_dict(location, raw, strict=strict)
    audience_raw = data.get("audience")
    audience: list[str] = []
    if isinstance(audience_raw, list):
        audience = [str(item).strip() for item in audience_raw if str(item or "").strip()]
    elif audience_raw is not None and strict:
        raise _validation_error(f"{location}.audience", "Must be a list of strings.")

    rules_raw = data.get("rules")
    if rules_raw is None:
        rules_list: list[Any] = []
    else:
        rules_list = _as_list(f"{location}.rules", rules_raw, strict=strict)

    rules: list[dict[str, Any]] = []
    for index, rule_item in enumerate(rules_list):
        rule_location = f"{location}.rules[{index}]"
        rule_data = _as_dict(rule_location, rule_item, strict=strict)
        rule_type = str(rule_data.get("type") or "").strip().lower()
        if not rule_type:
            if strict:
                raise _validation_error(rule_location, "Rule type is required.")
            continue
        rules.append(
            {
                "type": rule_type,
                "value": deepcopy(rule_data.get("value")),
                "operator": str(rule_data.get("operator") or "equals").strip().lower(),
            }
        )

    return {
        "enabled": bool(data.get("enabled", True)),
        "audience": audience,
        "rules": rules,
    }


def _normalize_data_source(raw: Any, location: str, *, strict: bool) -> dict[str, Any]:
    if raw in (None, "", {}):
        return {}
    if isinstance(raw, str):
        raw = {"type": raw}

    data = _as_dict(location, raw, strict=strict)
    source_type_raw = str(data.get("type") or data.get("source") or data.get("kind") or "").strip().lower()
    if not source_type_raw:
        return {}

    source_type = _SECTION_DATA_SOURCE_ALIASES.get(source_type_raw, source_type_raw)
    if source_type not in SUPPORTED_SECTION_DATA_SOURCE_TYPES:
        if strict:
            supported_types = ", ".join(sorted(SUPPORTED_SECTION_DATA_SOURCE_TYPES))
            raise _validation_error(
                f"{location}.type",
                f"Unsupported data source type '{source_type_raw}'. Supported values: {supported_types}.",
            )
        source_type = "static"

    if source_type == "none":
        return {"type": "none"}

    payload: dict[str, Any] = {"type": source_type}
    ref = str(data.get("ref") or data.get("id") or data.get("slug") or "").strip()
    if ref:
        payload["ref"] = ref
    params = _as_dict(f"{location}.params", data.get("params") or data.get("query"), strict=False)
    if params:
        payload["params"] = params
    return payload


def _normalize_section(item: Any, location: str, *, strict: bool, index: int) -> dict[str, Any]:
    data = _as_dict(location, item, strict=strict)

    section_type = str(data.get("type") or data.get("kind") or "").strip().lower()
    component = _normalize_component_key(
        data.get("component"),
        section_type,
        strict=strict,
        field=f"{location}.component",
    )
    section_id = str(data.get("id") or f"section-{uuid4().hex[:8]}").strip() or f"section-{uuid4().hex[:8]}"
    component_version = _as_int(
        f"{location}.component_version",
        data.get("component_version", data.get("version", 1)),
        default=1,
        minimum=1,
        strict=strict,
    )
    ordering = _as_int(
        f"{location}.ordering",
        data.get("ordering", data.get("order", index)),
        default=index,
        minimum=0,
        strict=strict,
    )

    children_raw = data.get("children")
    children_items = _as_list(f"{location}.children", children_raw, strict=strict) if children_raw is not None else []
    children = [
        _normalize_section(child, f"{location}.children[{child_index}]", strict=strict, index=child_index)
        for child_index, child in enumerate(children_items)
    ]

    data_source = _normalize_data_source(
        data.get("data_source") if data.get("data_source") is not None else data.get("source"),
        f"{location}.data_source",
        strict=strict,
    )

    section_payload = {
        "id": section_id,
        "type": section_type or component,
        "component": component,
        "component_version": component_version,
        "ordering": ordering,
        "props": _as_dict(f"{location}.props", data.get("props"), strict=False),
        "content": _as_dict(
            f"{location}.content",
            data.get("content") if data.get("content") is not None else data.get("data"),
            strict=False,
        ),
        "layout": _as_dict(f"{location}.layout", data.get("layout"), strict=False),
        "style_tokens": _as_dict(
            f"{location}.style_tokens",
            data.get("style_tokens") if data.get("style_tokens") is not None else data.get("style"),
            strict=False,
        ),
        "visibility": _normalize_visibility(data.get("visibility"), f"{location}.visibility", strict=strict),
        "children": children,
    }

    if data_source:
        section_payload["data_source"] = data_source

    slot = str(data.get("slot") or "").strip()
    if slot:
        section_payload["slot"] = slot
    return section_payload


def _normalize_sections(raw: Any, *, strict: bool) -> list[dict[str, Any]]:
    sections = _as_list("builder_data.sections", raw, strict=strict)
    return [
        _normalize_section(item, f"builder_data.sections[{index}]", strict=strict, index=index)
        for index, item in enumerate(sections)
    ]


def _normalize_locales(raw: Any, *, strict: bool) -> dict[str, Any]:
    locales = _as_dict("builder_data.locales", raw, strict=strict)
    normalized: dict[str, Any] = {}
    for locale_code, locale_payload in locales.items():
        key = str(locale_code or "").strip()
        if not key:
            continue
        locale_data = _as_dict(f"builder_data.locales.{key}", locale_payload, strict=strict)
        normalized[key] = {
            "meta": _as_dict(f"builder_data.locales.{key}.meta", locale_data.get("meta"), strict=False),
            "seo": _normalize_seo(locale_data.get("seo"), strict=False),
            "layout": _as_dict(f"builder_data.locales.{key}.layout", locale_data.get("layout"), strict=False),
            "style_tokens": _as_dict(
                f"builder_data.locales.{key}.style_tokens",
                locale_data.get("style_tokens"),
                strict=False,
            ),
            "sections": _normalize_sections(locale_data.get("sections"), strict=False),
        }
    return normalized


def _normalize_page_settings(raw: Any, *, strict: bool) -> dict[str, Any]:
    settings = _as_dict("page_settings", raw, strict=strict)
    document_mode = str(settings.get("document_mode") or "fragment").strip().lower()
    if document_mode not in {"fragment", "full_html"}:
        if strict:
            raise _validation_error("page_settings.document_mode", "Must be either 'fragment' or 'full_html'.")
        document_mode = "fragment"

    rendering = settings.get("rendering")
    rendering_data = rendering if isinstance(rendering, dict) else {}
    rendering_data = {
        **rendering_data,
        "source": "builder_data",
        "section_contract_version": SECTION_CONTRACT_VERSION,
    }

    return {
        **settings,
        "document_mode": document_mode,
        "rendering": rendering_data,
    }


def section_component_registry() -> list[dict[str, Any]]:
    """Return the stable list of allowed component identifiers for runtime rendering."""
    payload: list[dict[str, Any]] = []
    for key in sorted(SUPPORTED_SECTION_COMPONENT_KEYS):
        item = SECTION_COMPONENT_REGISTRY.get(key, {})
        payload.append(
            {
                "key": key,
                "label": str(item.get("label") or key),
                "category": str(item.get("category") or "content"),
                "data_sources": deepcopy(item.get("data_sources") or []),
            }
        )
    return payload


def normalize_block_template_builder_data(
    builder_data: Any,
    *,
    renderer_key: str,
    strict: bool,
) -> dict[str, Any]:
    """
    Normalize block/template payloads to the same renderer contract used by
    page sections. This keeps editor palette entries and runtime rendering
    aligned on stable component keys.
    """
    data = _as_dict("builder_data", builder_data, strict=strict)
    sections_input = data.get("sections")
    if sections_input is None and isinstance(data.get("blocks"), list):
        sections_input = data.get("blocks")
    if sections_input is None and isinstance(data.get("components"), list):
        sections_input = data.get("components")
    if sections_input is None:
        sections_input = [{"component": renderer_key, "props": {}, "content": {}, "style_tokens": {}}]

    normalized_sections = _normalize_sections(sections_input, strict=strict)
    metadata = _as_dict("builder_data.metadata", data.get("metadata"), strict=False)
    legacy = _as_dict("builder_data.legacy", data.get("legacy"), strict=False)
    for key, value in data.items():
        if key in {"schema_version", "metadata", "sections", "blocks", "components", "legacy"}:
            continue
        legacy[key] = deepcopy(value)

    normalized_builder_data: dict[str, Any] = {
        "schema_version": PAGE_SCHEMA_VERSION,
        "section_contract": {
            "version": SECTION_CONTRACT_VERSION,
            "registry": "nextjs",
            "allowed_data_sources": sorted(SUPPORTED_SECTION_DATA_SOURCE_TYPES),
        },
        "metadata": metadata,
        "sections": normalized_sections,
    }
    if legacy:
        normalized_builder_data["legacy"] = legacy
    return normalized_builder_data


def extract_render_cache(
    builder_data: Any,
    html: Any = "",
    css: Any = "",
    js: Any = "",
    *,
    cache_first: bool = True,
) -> dict[str, str]:
    data = builder_data if isinstance(builder_data, dict) else {}
    raw_cache = data.get("render_cache")
    cache = raw_cache if isinstance(raw_cache, dict) else {}

    def _coalesce(primary: Any, fallback: Any) -> str:
        if primary in (None, ""):
            return str(fallback or "")
        return str(primary)

    if cache_first:
        html_value = _coalesce(cache.get("html"), html)
        css_value = _coalesce(cache.get("css"), css)
        js_value = _coalesce(cache.get("js"), js)
    else:
        html_value = _coalesce(html, cache.get("html"))
        css_value = _coalesce(css, cache.get("css"))
        js_value = _coalesce(js, cache.get("js"))

    return {
        "html": html_value,
        "css": css_value,
        "js": js_value,
    }


def extract_page_summary(builder_data: Any) -> str:
    if not isinstance(builder_data, dict):
        return ""

    metadata = builder_data.get("metadata")
    if isinstance(metadata, dict):
        description = str(metadata.get("description") or "").strip()
        if description:
            return description

    seo = builder_data.get("seo")
    if isinstance(seo, dict):
        description = str(seo.get("meta_description") or "").strip()
        if description:
            return description

    sections = builder_data.get("sections")
    if not isinstance(sections, list):
        return ""

    def _visit(section_items: list[Any]) -> str:
        for section in section_items:
            if not isinstance(section, dict):
                continue
            content = section.get("content")
            if isinstance(content, dict):
                for key in ("summary", "description", "text", "body", "subtitle"):
                    candidate = str(content.get(key) or "").strip()
                    if candidate:
                        return candidate
            children = section.get("children")
            if isinstance(children, list):
                child_summary = _visit(children)
                if child_summary:
                    return child_summary
        return ""

    return _visit(sections)


def normalize_page_content(
    *,
    title: str,
    slug: str,
    path: str,
    is_homepage: bool,
    status: str,
    locale_code: str | None,
    builder_data: Any,
    seo: Any,
    page_settings: Any,
    html: Any = "",
    css: Any = "",
    js: Any = "",
    schema_version: Any = None,
    strict: bool = True,
) -> dict[str, Any]:
    data = _as_dict("builder_data", builder_data, strict=strict)
    version_value = schema_version if schema_version not in (None, "") else data.get("schema_version")
    normalized_schema_version = _normalize_schema_version(version_value, strict=strict)

    route_data = _as_dict("builder_data.route", data.get("route"), strict=False)
    normalized_slug = slugify(slug or route_data.get("slug") or title) or "page"
    normalized_path = normalize_route_path(
        path or route_data.get("path"),
        is_homepage=is_homepage,
        slug=normalized_slug,
    )

    sections_input = data.get("sections")
    if sections_input is None and isinstance(data.get("blocks"), list):
        sections_input = data.get("blocks")
    if sections_input is None and isinstance(data.get("components"), list):
        sections_input = data.get("components")

    normalized_seo = _normalize_seo(seo if seo is not None else data.get("seo"), strict=strict)
    normalized_settings = _normalize_page_settings(page_settings, strict=strict)
    normalized_layout = _as_dict("builder_data.layout", data.get("layout"), strict=False)
    if not normalized_layout and isinstance(normalized_settings.get("layout"), dict):
        normalized_layout = deepcopy(normalized_settings["layout"])
    normalized_style_tokens = _as_dict("builder_data.style_tokens", data.get("style_tokens"), strict=False)
    normalized_sections = _normalize_sections(sections_input, strict=strict)
    normalized_locales = _normalize_locales(data.get("locales"), strict=False)

    metadata = _as_dict("builder_data.metadata", data.get("metadata"), strict=False)
    metadata = {
        **metadata,
        "title": str(title or metadata.get("title") or "").strip(),
        "slug": normalized_slug,
        "path": normalized_path,
        "is_homepage": bool(is_homepage),
        "status": str(status or metadata.get("status") or "").strip(),
        "locale_code": str(locale_code or metadata.get("locale_code") or "").strip(),
    }

    render_cache = extract_render_cache(data, html=html, css=css, js=js, cache_first=False)
    legacy = _as_dict("builder_data.legacy", data.get("legacy"), strict=False)
    for key, value in data.items():
        if key in _CANONICAL_SCHEMA_KEYS:
            continue
        legacy[key] = deepcopy(value)

    normalized_builder_data = {
        "schema_version": normalized_schema_version,
        "metadata": metadata,
        "route": {
            "slug": normalized_slug,
            "path": normalized_path,
            "is_homepage": bool(is_homepage),
        },
        "seo": normalized_seo,
        "layout": normalized_layout,
        "style_tokens": normalized_style_tokens,
        "section_contract": {
            "version": SECTION_CONTRACT_VERSION,
            "registry": "nextjs",
            "allowed_data_sources": sorted(SUPPORTED_SECTION_DATA_SOURCE_TYPES),
        },
        "sections": normalized_sections,
        "locales": normalized_locales,
        "render_cache": render_cache,
    }
    if legacy:
        normalized_builder_data["legacy"] = legacy

    return {
        "schema_version": normalized_schema_version,
        "slug": normalized_slug,
        "path": normalized_path,
        "builder_data": normalized_builder_data,
        "seo": normalized_seo,
        "page_settings": normalized_settings,
        "html": render_cache["html"],
        "css": render_cache["css"],
        "js": render_cache["js"],
    }


__all__ = [
    "BLOCK_TEMPLATE_CATEGORY_DEFAULT_COMPONENTS",
    "PAGE_SCHEMA_VERSION",
    "SECTION_COMPONENT_ALIASES",
    "SECTION_COMPONENT_REGISTRY",
    "SECTION_CONTRACT_VERSION",
    "SUPPORTED_PAGE_SCHEMA_VERSIONS",
    "SUPPORTED_SECTION_COMPONENT_KEYS",
    "SUPPORTED_SECTION_DATA_SOURCE_TYPES",
    "default_renderer_key_for_block_category",
    "extract_page_summary",
    "extract_render_cache",
    "normalize_block_template_builder_data",
    "normalize_block_template_renderer_key",
    "normalize_component_key",
    "normalize_page_content",
    "normalize_route_path",
    "section_component_registry",
]
