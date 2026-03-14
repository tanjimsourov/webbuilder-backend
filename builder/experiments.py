import hashlib
import json
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from .localization import select_best_locale
from .models import ExperimentEvent, Page, PageExperiment, PageExperimentVariant, PageTranslation, Site, SiteLocale
from .services import normalize_page_path


VISITOR_COOKIE_NAME = "wb_vid"
ASSIGNMENTS_COOKIE_NAME = "wb_exp"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def normalize_experiment_key(value: str) -> str:
    return slugify(value or "") or "experiment"


def get_scoped_page_experiments(page: Page, locale: SiteLocale | None):
    queryset = (
        PageExperiment.objects.select_related("site", "page", "locale")
        .prefetch_related("variants")
        .filter(page=page)
        .order_by("-updated_at", "name")
    )
    if locale and not locale.is_default:
        return queryset.filter(locale=locale)
    return queryset.filter(locale__isnull=True)


def is_experiment_live(experiment: PageExperiment, now=None) -> bool:
    if experiment.status != PageExperiment.STATUS_ACTIVE:
        return False
    now = now or timezone.now()
    if experiment.starts_at and experiment.starts_at > now:
        return False
    if experiment.ends_at and experiment.ends_at <= now:
        return False
    return True


def device_type_from_request(request) -> str:
    agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if "ipad" in agent or "tablet" in agent:
        return "tablet"
    if "mobile" in agent or "android" in agent or "iphone" in agent:
        return "mobile"
    return "desktop"


def audience_matches_request(audience: dict | None, request, locale_code: str = "") -> bool:
    audience = audience or {}
    if not audience:
        return True

    normalized_locale = (locale_code or "").lower()
    locale_targets = [str(item).lower() for item in audience.get("locales", []) if item]
    if locale_targets and normalized_locale not in locale_targets:
        return False

    device_targets = [str(item).lower() for item in audience.get("device_types", []) if item]
    if device_targets and device_type_from_request(request) not in device_targets:
        return False

    for query_key in ("utm_source", "utm_medium", "utm_campaign"):
        expected_values = [str(item).lower() for item in audience.get(query_key, []) if item]
        current_value = (request.GET.get(query_key) or "").lower()
        if expected_values and current_value not in expected_values:
            return False

    path_contains = [str(item).lower() for item in audience.get("path_contains", []) if item]
    request_path = (request.path or "").lower()
    if path_contains and not any(item in request_path for item in path_contains):
        return False

    query_rules = audience.get("query", {}) or {}
    for key, expected in query_rules.items():
        actual = request.GET.get(str(key), "")
        if isinstance(expected, list):
            if actual not in [str(item) for item in expected]:
                return False
        elif actual != str(expected):
            return False

    return True


def _bucket_value(visitor_id: str, seed: str) -> float:
    digest = hashlib.sha256(f"{visitor_id}:{seed}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def _pick_weighted_variant(visitor_id: str, experiment: PageExperiment, variants: list[PageExperimentVariant]) -> PageExperimentVariant:
    total_weight = sum(max(variant.weight, 1) for variant in variants)
    target = _bucket_value(visitor_id, f"{experiment.key}:variation") * total_weight
    cursor = 0.0
    for variant in variants:
        cursor += max(variant.weight, 1)
        if target < cursor:
            return variant
    return variants[-1]


def parse_assignment_cookie(raw_value: str | None) -> dict[int, int]:
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    parsed: dict[int, int] = {}
    for key, value in payload.items():
        try:
            parsed[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return parsed


def serialize_assignment_cookie(assignments: dict[int, int]) -> str:
    return json.dumps({str(key): value for key, value in assignments.items()}, separators=(",", ":"))


def parse_forced_variants(raw_value: str | None) -> dict[str, str]:
    if not raw_value:
        return {}
    payload: dict[str, str] = {}
    for item in str(raw_value).split(","):
        pair = item.strip()
        if not pair or ":" not in pair:
            continue
        experiment_key, variant_key = pair.split(":", 1)
        normalized_experiment_key = normalize_experiment_key(experiment_key)
        normalized_variant_key = slugify(variant_key) or ""
        if normalized_experiment_key and normalized_variant_key:
            payload[normalized_experiment_key] = normalized_variant_key
    return payload


def evaluate_page_experiments(request, page: Page, locale: SiteLocale | None):
    existing_visitor_id = (request.COOKIES.get(VISITOR_COOKIE_NAME) or "").strip()
    visitor_id = existing_visitor_id or uuid.uuid4().hex
    visitor_cookie_changed = visitor_id != existing_visitor_id

    cookie_assignments = parse_assignment_cookie(request.COOKIES.get(ASSIGNMENTS_COOKIE_NAME))
    updated_assignments = dict(cookie_assignments)
    assignment_cookie_changed = False
    forced_variants = parse_forced_variants(request.GET.get("exp"))
    locale_code = locale.code.lower() if locale else ""
    assignments: list[dict[str, object]] = []

    for experiment in get_scoped_page_experiments(page, locale):
        enabled_variants = [variant for variant in experiment.variants.all() if variant.is_enabled]
        if len(enabled_variants) < 2:
            continue

        forced_variant = None
        forced_variant_key = forced_variants.get(experiment.key)
        if forced_variant_key:
            forced_variant = next((variant for variant in enabled_variants if variant.key == forced_variant_key), None)

        if not forced_variant:
            if not is_experiment_live(experiment):
                continue
            if not audience_matches_request(experiment.audience, request, locale_code=locale_code):
                continue

        assignment_variant = forced_variant
        is_forced = assignment_variant is not None

        if assignment_variant is None:
            cookie_variant_id = updated_assignments.get(experiment.id)
            assignment_variant = next((variant for variant in enabled_variants if variant.id == cookie_variant_id), None)

        if assignment_variant is None:
            coverage = experiment.coverage_percent / 100.0
            if _bucket_value(visitor_id, experiment.key) >= coverage:
                continue
            assignment_variant = _pick_weighted_variant(visitor_id, experiment, enabled_variants)
            updated_assignments[experiment.id] = assignment_variant.id
            assignment_cookie_changed = True

        assignments.append(
            {
                "experiment": experiment,
                "variant": assignment_variant,
                "forced": is_forced,
            }
        )

        if not is_forced:
            ExperimentEvent.objects.get_or_create(
                experiment=experiment,
                visitor_id=visitor_id,
                event_type=ExperimentEvent.EVENT_EXPOSURE,
                goal_key="",
                defaults={
                    "variant": assignment_variant,
                    "site": experiment.site,
                    "page": page,
                    "locale_code": locale_code,
                    "request_path": request.path[:255],
                    "metadata": {
                        "device_type": device_type_from_request(request),
                        "query": {key: value for key, value in request.GET.items()},
                    },
                },
            )

    return {
        "visitor_id": visitor_id,
        "visitor_cookie_changed": visitor_cookie_changed,
        "assignments": assignments,
        "assignment_cookie": updated_assignments,
        "assignment_cookie_changed": assignment_cookie_changed,
    }


def apply_variant_to_page_payload(payload: dict[str, object], assignments: list[dict[str, object]]) -> dict[str, object]:
    next_payload = {
        **payload,
        "seo": dict(payload.get("seo") or {}),
        "page_settings": dict(payload.get("page_settings") or {}),
        "builder_data": dict(payload.get("builder_data") or {}),
    }
    for item in assignments:
        variant = item.get("variant")
        if not isinstance(variant, PageExperimentVariant):
            continue
        if variant.title:
            next_payload["title"] = variant.title
        if variant.seo:
            next_payload["seo"] = {**dict(next_payload.get("seo") or {}), **variant.seo}
        if variant.page_settings:
            next_payload["page_settings"] = {
                **dict(next_payload.get("page_settings") or {}),
                **variant.page_settings,
            }
        if variant.builder_data:
            next_payload["builder_data"] = variant.builder_data
        if variant.html:
            next_payload["html"] = variant.html
        if variant.css:
            next_payload["css"] = variant.css
        if variant.js:
            next_payload["js"] = variant.js
    return next_payload


def persist_experiment_cookies(
    response,
    visitor_id: str,
    assignment_cookie: dict[int, int],
    visitor_cookie_changed: bool = False,
    assignment_cookie_changed: bool = False,
):
    cookie_options = {
        "max_age": COOKIE_MAX_AGE,
        "httponly": True,
        "samesite": "Lax",
        "secure": bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
    }
    if visitor_cookie_changed:
        response.set_cookie(VISITOR_COOKIE_NAME, visitor_id, **cookie_options)
    if assignment_cookie_changed and assignment_cookie:
        response.set_cookie(ASSIGNMENTS_COOKIE_NAME, serialize_assignment_cookie(assignment_cookie), **cookie_options)
    return response


def record_conversion_from_assignments(
    request,
    site: Site,
    page: Page | None,
    locale: SiteLocale | None,
    form_name: str,
    request_path: str = "",
    metadata: dict | None = None,
):
    if not page:
        return
    visitor_id = (request.COOKIES.get(VISITOR_COOKIE_NAME) or "").strip()
    if not visitor_id:
        return
    assignment_cookie = parse_assignment_cookie(request.COOKIES.get(ASSIGNMENTS_COOKIE_NAME))
    if not assignment_cookie:
        return

    locale_code = locale.code.lower() if locale else ""
    experiment_map = {
        experiment.id: experiment
        for experiment in get_scoped_page_experiments(page, locale)
        .filter(id__in=list(assignment_cookie.keys()))
        .prefetch_related("variants")
    }
    normalized_form_name = (form_name or "").strip().lower()
    for experiment_id, variant_id in assignment_cookie.items():
        experiment = experiment_map.get(experiment_id)
        if not experiment or not is_experiment_live(experiment):
            continue
        if experiment.goal_form_name and experiment.goal_form_name.strip().lower() != normalized_form_name:
            continue
        variant = next((item for item in experiment.variants.all() if item.id == variant_id), None)
        if not variant:
            continue
        ExperimentEvent.objects.get_or_create(
            experiment=experiment,
            visitor_id=visitor_id,
            event_type=ExperimentEvent.EVENT_CONVERSION,
            goal_key=experiment.goal_form_name or form_name,
            defaults={
                "variant": variant,
                "site": site,
                "page": page,
                "locale_code": locale_code,
                "request_path": request_path[:255],
                "metadata": {
                    "form_name": form_name,
                    **(metadata or {}),
                },
            },
        )


def resolve_public_page_context(site: Site, raw_page_path: str | None):
    raw_page_path = (raw_page_path or "").strip()
    locale = None
    translation = None

    if raw_page_path:
        path_value = urlsplit(raw_page_path).path or raw_page_path
    else:
        path_value = ""

    normalized_path = "/"
    if path_value:
        segments = [segment for segment in path_value.split("/") if segment]
        if len(segments) >= 2 and segments[0] == "preview" and segments[1] == site.slug:
            remaining_segments = segments[2:]
            locales = list(site.locales.filter(is_enabled=True).order_by("-is_default", "code"))
            if remaining_segments and locales:
                matched_locale_code = None
                try:
                    matched_locale_code = select_best_locale(
                        remaining_segments[0],
                        [item.code for item in locales],
                    )
                except ValueError:
                    matched_locale_code = None
                if matched_locale_code:
                    locale = next((item for item in locales if item.code == matched_locale_code), None)
                    remaining_segments = remaining_segments[1:]
            normalized_path = "/" if not remaining_segments else f"/{'/'.join(remaining_segments)}/"
        else:
            normalized_path = "/" if path_value == "/" else normalize_page_path(path_value, False)

    if locale and not locale.is_default:
        translation = (
            PageTranslation.objects.select_related("page", "locale")
            .filter(page__site=site, locale=locale, path=normalized_path)
            .first()
        )
        if translation:
            return translation.page, translation, locale, normalized_path

    if normalized_path != "/":
        translation = (
            PageTranslation.objects.select_related("page", "locale")
            .filter(page__site=site, path=normalized_path, locale__is_enabled=True)
            .first()
        )
        if translation:
            return translation.page, translation, translation.locale, normalized_path

    page = site.pages.filter(path=normalized_path).first()
    if not page and normalized_path == "/":
        page = site.pages.filter(is_homepage=True).first()
    if not page:
        return None, None, locale, normalized_path

    if locale and not locale.is_default:
        translation = page.translations.filter(locale=locale).select_related("locale").first()
    return page, translation, locale, normalized_path
