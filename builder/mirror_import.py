from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from .models import Page, Site
from .services import create_revision


IMPORT_MANIFEST_NAMES = ("manifest.json", "_manifest.json")
ATTRIBUTE_URL_RE = re.compile(
    r'(?P<prefix>\b(?:href|src|action|content)=["\'])(?P<url>/[^"\']*|https?://[^"\']*)(?P<suffix>["\'])',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?P<name>description|og:title|og:description)["\'][^>]+content=["\'](?P<content>.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)


def preview_url_for_route(site_slug: str, route_path: str) -> str:
    suffix = "" if route_path == "/" else route_path.lstrip("/")
    return f"/preview/{site_slug}/{suffix}".rstrip("/")


def normalize_import_path(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.strip()
    if not path or path == "/":
        return "/"
    return f'/{path.strip("/")}/'


def mirror_import_root() -> Path:
    root = Path(getattr(settings, "MIRROR_IMPORT_ROOT", settings.BASE_DIR / ".mirror-imports")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolve_mirror_source_path(source_path: str) -> Path:
    root = mirror_import_root()
    candidate = Path(source_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Mirror imports are limited to: {root}") from exc
    return resolved


def serialize_mirror_path(path: Path) -> str:
    root = mirror_import_root()
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.name


def discover_manifest(source_path: str) -> tuple[Path, Path]:
    source = resolve_mirror_source_path(source_path)
    if not source.exists():
        raise ValueError(f"Source path does not exist: {source}")

    if source.is_file():
        if source.name not in IMPORT_MANIFEST_NAMES:
            raise ValueError("Source file must be a mirror manifest.")
        return source, source.parent

    candidate_paths = [
        source / "manifest.json",
        source / "_manifest.json",
        source / "output" / "smc-pages" / "manifest.json",
        source / "public" / "mirror" / "_manifest.json",
        source / "smc_be" / "public" / "mirror" / "_manifest.json",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            return candidate, source

    for name in IMPORT_MANIFEST_NAMES:
        found = next(source.rglob(name), None)
        if found:
            return found, source

    raise ValueError(f"No mirror manifest found under: {source}")


def resolve_manifest_entry_file(manifest_path: Path, source_root: Path, entry_file: str) -> Path:
    relative = Path(entry_file.replace("\\", "/"))
    candidates = []
    if relative.is_absolute():
        candidates.append(relative)

    roots = [source_root, manifest_path.parent, *manifest_path.parents]
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        candidates.append(root / relative)
        candidates.append(root / relative.name)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise ValueError(f"Mirror HTML file could not be resolved: {entry_file}")


def extract_document_title(document_html: str, route_path: str) -> str:
    match = TITLE_RE.search(document_html)
    if not match:
        if route_path == "/":
            return "Homepage"
        return route_path.strip("/").split("/")[-1].replace("-", " ").title()

    title = html.unescape(re.sub(r"\s+", " ", match.group("title"))).strip()
    if "|" in title:
        title = title.split("|", 1)[0].strip()
    return title or "Imported page"


def extract_seo_fields(document_html: str, fallback_title: str) -> dict[str, str]:
    seo = {
        "meta_title": fallback_title[:60],
        "meta_description": "",
    }
    for match in META_RE.finditer(document_html):
        name = match.group("name").lower()
        content = html.unescape(re.sub(r"\s+", " ", match.group("content"))).strip()
        if not content:
            continue
        if name == "description" and not seo["meta_description"]:
            seo["meta_description"] = content[:155]
        if name == "og:title":
            seo["meta_title"] = content[:60]
        if name == "og:description" and not seo["meta_description"]:
            seo["meta_description"] = content[:155]
    return seo


def build_slug_for_route(route_path: str) -> str:
    if route_path == "/":
        return "home"
    pieces = [part for part in route_path.strip("/").split("/") if part]
    return slugify(pieces[-1] if pieces else "page") or "page"


def rewrite_document_html(
    document_html: str,
    *,
    site_slug: str,
    source_origin: str,
    imported_routes: set[str],
) -> str:
    preview_map = {route: preview_url_for_route(site_slug, route) for route in imported_routes}

    absolute_replacements: list[tuple[str, str]] = []
    for route in sorted(imported_routes, key=len, reverse=True):
        preview_url = preview_map[route]
        if route == "/":
            absolute_variants = [f"{source_origin}/"]
        else:
            absolute_variants = [
                f"{source_origin}{route.rstrip('/')}",
                f"{source_origin}{route}",
            ]
        for variant in absolute_variants:
            absolute_replacements.append((variant, preview_url))

    for original, replacement in absolute_replacements:
        document_html = document_html.replace(original, replacement)
        document_html = document_html.replace(original.replace("/", r"\/"), replacement.replace("/", r"\/"))

    def replace_attribute(match: re.Match[str]) -> str:
        raw_url = match.group("url")
        parsed = urlparse(raw_url)
        target_url = raw_url

        if parsed.scheme and parsed.netloc:
            absolute_origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")
            if absolute_origin == source_origin:
                normalized = normalize_import_path(parsed.path)
                if normalized in preview_map:
                    target_url = preview_map[normalized]
                    if parsed.query:
                        target_url += f"?{parsed.query}"
                    if parsed.fragment:
                        target_url += f"#{parsed.fragment}"
                else:
                    target_url = f"{source_origin}{parsed.path or '/'}"
                    if parsed.query:
                        target_url += f"?{parsed.query}"
                    if parsed.fragment:
                        target_url += f"#{parsed.fragment}"
        elif raw_url.startswith("/"):
            normalized = normalize_import_path(parsed.path)
            if normalized in preview_map:
                target_url = preview_map[normalized]
                if parsed.query:
                    target_url += f"?{parsed.query}"
                if parsed.fragment:
                    target_url += f"#{parsed.fragment}"
            else:
                target_url = f"{source_origin}{parsed.path or '/'}"
                if parsed.query:
                    target_url += f"?{parsed.query}"
                if parsed.fragment:
                    target_url += f"#{parsed.fragment}"

        return f'{match.group("prefix")}{target_url}{match.group("suffix")}'

    return ATTRIBUTE_URL_RE.sub(replace_attribute, document_html)


def import_mirrored_site(
    site: Site,
    *,
    source_path: str,
    publish: bool = True,
    replace_existing: bool = True,
) -> dict[str, object]:
    manifest_path, source_root = discover_manifest(source_path)
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise ValueError("Mirror manifest is empty or invalid.")

    import_items: list[dict[str, object]] = []
    source_origin = ""

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        entry_file = str(entry.get("file") or "").strip()
        code = str(entry.get("code") or "")
        if not url or not entry_file or code not in {"200", "200.0"}:
            continue

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            continue
        if not source_origin:
            source_origin = f"{parsed.scheme}://{parsed.netloc}"

        html_path = resolve_manifest_entry_file(manifest_path, source_root, entry_file)
        if html_path.suffix.lower() != ".html":
            continue

        route_path = normalize_import_path(parsed.path)
        document_html = html_path.read_text(encoding="utf-8", errors="ignore")
        title = extract_document_title(document_html, route_path)
        import_items.append(
            {
                "url": url,
                "path": route_path,
                "slug": build_slug_for_route(route_path),
                "title": title,
                "seo": extract_seo_fields(document_html, title),
                "html": document_html,
            }
        )

    if not import_items:
        raise ValueError("No importable HTML pages were found in the mirror manifest.")

    if not source_origin:
        raise ValueError("Mirror manifest did not provide a valid source origin.")

    imported_routes = {item["path"] for item in import_items}
    now = timezone.now()

    existing_by_path = {}
    if replace_existing:
        site.pages.all().delete()
    else:
        existing_by_path = {page.path: page for page in site.pages.all()}

    imported_pages: list[Page] = []
    for item in import_items:
        page = existing_by_path.get(item["path"]) or Page(site=site, path=item["path"])
        page.title = str(item["title"])
        page.slug = str(item["slug"])
        page.is_homepage = item["path"] == "/"
        page.status = Page.STATUS_PUBLISHED if publish else Page.STATUS_DRAFT
        page.seo = dict(item["seo"])
        page.page_settings = {
            **(page.page_settings or {}),
            "document_mode": "full_html",
            "mirror_source_url": str(item["url"]),
            "mirror_source_origin": source_origin,
        }
        page.builder_data = {}
        page.css = ""
        page.js = ""
        page.html = rewrite_document_html(
            str(item["html"]),
            site_slug=site.slug,
            source_origin=source_origin,
            imported_routes=imported_routes,
        )
        page.published_at = now if publish else None
        page.save()
        create_revision(page, "Imported mirror snapshot")
        imported_pages.append(page)

    site.settings = {
        **(site.settings or {}),
        "mirror_import": {
            "source_path": serialize_mirror_path(resolve_mirror_source_path(source_path)),
            "manifest_path": serialize_mirror_path(manifest_path),
            "source_origin": source_origin,
            "publish": publish,
            "replace_existing": replace_existing,
            "imported_at": now.isoformat(),
            "imported_pages": len(imported_pages),
        },
    }
    site.save(update_fields=["settings", "updated_at"])

    homepage = next((page for page in imported_pages if page.is_homepage), None)
    return {
        "imported_pages": len(imported_pages),
        "homepage_page_id": homepage.id if homepage else None,
        "source_origin": source_origin,
        "manifest_path": serialize_mirror_path(manifest_path),
    }
