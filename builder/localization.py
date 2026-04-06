import re
from typing import Iterable

from django.db import transaction
from django.utils.text import slugify

from cms.page_schema import normalize_page_content

LOCALE_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
RTL_LANGUAGE_CODES = {"ar", "fa", "he", "ku", "ps", "sd", "ug", "ur"}


def normalize_locale_code(value: str) -> str:
    cleaned = (value or "").strip().replace("_", "-")
    if not cleaned or not LOCALE_CODE_RE.match(cleaned):
        raise ValueError("Locale codes must use a valid BCP 47 style tag, for example en, fr, or pt-BR.")

    parts = [part for part in cleaned.split("-") if part]
    normalized_parts: list[str] = [parts[0].lower()]

    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized_parts.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized_parts.append(part.title())
        else:
            normalized_parts.append(part.lower())

    return "-".join(normalized_parts)


def locale_direction(code: str) -> str:
    language = normalize_locale_code(code).split("-", 1)[0]
    return "rtl" if language in RTL_LANGUAGE_CODES else "ltr"


def normalize_translation_path(slug: str, is_homepage: bool) -> str:
    if is_homepage:
        return "/"
    clean_slug = slug.strip("/") or "page"
    return f"/{clean_slug}/"


def localized_preview_url(site_slug: str, path: str, locale_code: str | None = None, is_homepage: bool = False) -> str:
    suffix = "" if is_homepage else path.lstrip("/")
    if locale_code:
        return f"/preview/{site_slug}/{normalize_locale_code(locale_code).lower()}/{suffix}".rstrip("/")
    return f"/preview/{site_slug}/{suffix}".rstrip("/")


def select_best_locale(requested_locale: str | None, available_codes: Iterable[str]) -> str | None:
    available = [normalize_locale_code(code) for code in available_codes if code]
    if not available:
        return None
    if not requested_locale:
        return available[0]

    requested = normalize_locale_code(requested_locale)
    if requested in available:
        return requested

    requested_language = requested.split("-", 1)[0]
    for code in available:
        if code.split("-", 1)[0] == requested_language:
            return code
    return None


def clone_page_translation_content(page, locale):
    from .models import PageTranslation

    translation, created = PageTranslation.objects.get_or_create(
        page=page,
        locale=locale,
        defaults={
            "title": page.title,
            "slug": page.slug,
            "path": normalize_translation_path(page.slug, page.is_homepage),
            "seo": page.seo or {},
            "page_settings": page.page_settings or {},
            "builder_schema_version": page.builder_schema_version,
            "builder_data": page.builder_data or {},
            "html": page.html or "",
            "css": page.css or "",
            "js": page.js or "",
            "status": PageTranslation.STATUS_DRAFT,
        },
    )
    return translation, created


@transaction.atomic
def sync_site_localization_settings(site) -> dict:
    locales = list(site.locales.order_by("-is_default", "code"))
    if not locales:
        settings = {**(site.settings or {})}
        localization = settings.get("localization") or {}
        localization.update(
            {
                "enabled": False,
                "default_locale": "",
                "available_locales": [],
                "fallback_locale": "",
            }
        )
        settings["localization"] = localization
        site.settings = settings
        site.save(update_fields=["settings", "updated_at"])
        return localization

    default_locale = next((locale for locale in locales if locale.is_default), locales[0])
    if not default_locale.is_default:
        default_locale.is_default = True
        default_locale.save(update_fields=["is_default", "updated_at"])

    settings = {**(site.settings or {})}
    localization = settings.get("localization") or {}
    localization.update(
        {
            "enabled": len(locales) > 0,
            "default_locale": default_locale.code,
            "available_locales": [locale.code for locale in locales if locale.is_enabled],
            "fallback_locale": default_locale.code,
        }
    )
    settings["localization"] = localization
    site.settings = settings
    site.save(update_fields=["settings", "updated_at"])
    return localization


def ensure_site_locale(site, code: str, is_default: bool = False):
    from .models import SiteLocale

    normalized_code = normalize_locale_code(code)
    locale, created = SiteLocale.objects.get_or_create(
        site=site,
        code=normalized_code,
        defaults={
            "direction": locale_direction(normalized_code),
            "is_default": is_default,
        },
    )
    changed = False
    if locale.direction != locale_direction(normalized_code):
        locale.direction = locale_direction(normalized_code)
        changed = True
    if is_default and not locale.is_default:
        locale.is_default = True
        changed = True
    if changed:
        locale.save(update_fields=["direction", "is_default", "updated_at"])
    if is_default:
        locale.site.locales.exclude(pk=locale.pk).filter(is_default=True).update(is_default=False)
    sync_site_localization_settings(site)
    return locale, created


def sync_translation_paths(page) -> None:
    for translation in page.translations.all():
        desired_path = normalize_translation_path(translation.slug, page.is_homepage)
        if translation.path != desired_path:
            translation.path = desired_path
            translation.save(update_fields=["path", "updated_at"])


def build_translation_payload(translation, payload: dict) -> None:
    if "title" in payload:
        translation.title = payload["title"]

    translation.slug = slugify(payload.get("slug", translation.slug) or translation.title) or "page"
    translation.path = normalize_translation_path(translation.slug, translation.page.is_homepage)

    if "seo" in payload:
        translation.seo = payload["seo"] or {}
    if "page_settings" in payload:
        translation.page_settings = payload["page_settings"] or {}
    if "builder_schema_version" in payload:
        translation.builder_schema_version = payload["builder_schema_version"]
    if "builder_data" in payload:
        translation.builder_data = payload["builder_data"] or {}
    if "project_data" in payload:
        translation.builder_data = payload["project_data"] or {}
    if "html" in payload:
        translation.html = payload["html"] or ""
    if "css" in payload:
        translation.css = payload["css"] or ""
    if "js" in payload:
        translation.js = payload["js"] or ""

    strict_schema_validation = any(
        key in payload for key in ("builder_data", "project_data", "seo", "page_settings", "builder_schema_version")
    )
    normalized = normalize_page_content(
        title=translation.title,
        slug=translation.slug,
        path=translation.path,
        is_homepage=translation.page.is_homepage,
        status=translation.status,
        locale_code=translation.locale.code if translation.locale_id else "",
        builder_data=translation.builder_data,
        seo=translation.seo,
        page_settings=translation.page_settings,
        html=translation.html,
        css=translation.css,
        js=translation.js,
        schema_version=translation.builder_schema_version,
        strict=strict_schema_validation,
    )
    translation.builder_schema_version = normalized["schema_version"]
    translation.builder_data = normalized["builder_data"]
    translation.seo = normalized["seo"]
    translation.page_settings = normalized["page_settings"]
    translation.html = normalized["html"]
    translation.css = normalized["css"]
    translation.js = normalized["js"]
