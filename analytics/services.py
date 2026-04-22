"""Analytics domain services."""

from __future__ import annotations

import hashlib
import ipaddress
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.utils import timezone

from analytics.models import AnalyticsEvent, AnalyticsRollup, AnalyticsSession, CommerceAnalyticsEvent
from builder import seo_services
from shared.http.context import get_request_id

BOT_SIGNATURES = (
    "bot",
    "spider",
    "crawler",
    "curl",
    "wget",
    "httpclient",
    "python-requests",
    "headless",
    "slurp",
    "bingpreview",
)


@dataclass(frozen=True)
class ClientContext:
    ip_hash: str
    ip_prefix: str
    user_agent_hash: str
    device_type: str
    browser: str
    os: str
    is_bot: bool
    referrer_domain: str


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


def track_commerce_event(
    *,
    site: Any,
    event_name: str,
    payload: dict[str, Any] | None = None,
    aggregate_type: str = "",
    aggregate_id: str = "",
) -> CommerceAnalyticsEvent:
    return CommerceAnalyticsEvent.objects.create(
        site=site,
        event_name=event_name,
        aggregate_type=aggregate_type[:60],
        aggregate_id=str(aggregate_id or "")[:120],
        request_id=get_request_id() or "",
        payload=payload or {},
    )


def _extract_client_ip(request) -> str:
    forwarded_for = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded_for or (request.META.get("REMOTE_ADDR") or "")


def _ip_prefix(ip_value: str) -> str:
    if not ip_value:
        return ""
    try:
        parsed = ipaddress.ip_address(ip_value)
    except ValueError:
        return ""
    if parsed.version == 4:
        network = ipaddress.ip_network(f"{ip_value}/24", strict=False)
        return str(network.network_address)
    network = ipaddress.ip_network(f"{ip_value}/64", strict=False)
    return str(network.network_address)


def _digest(value: str) -> str:
    salt = (
        getattr(settings, "ANALYTICS_HASH_SALT", "")
        or getattr(settings, "SECRET_KEY", "")
        or "analytics-salt"
    )
    payload = f"{salt}:{value}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _detect_device_type(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if any(signature in ua for signature in BOT_SIGNATURES):
        return AnalyticsSession.DEVICE_BOT
    if "tablet" in ua or "ipad" in ua:
        return AnalyticsSession.DEVICE_TABLET
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return AnalyticsSession.DEVICE_MOBILE
    if ua:
        return AnalyticsSession.DEVICE_DESKTOP
    return AnalyticsSession.DEVICE_UNKNOWN


def _detect_browser(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "edg/" in ua:
        return "Edge"
    if "chrome/" in ua and "edg/" not in ua:
        return "Chrome"
    if "firefox/" in ua:
        return "Firefox"
    if "safari/" in ua and "chrome/" not in ua:
        return "Safari"
    if "opera" in ua or "opr/" in ua:
        return "Opera"
    return "Unknown"


def _detect_os(user_agent: str) -> str:
    ua = (user_agent or "").lower()
    if "windows" in ua:
        return "Windows"
    if "mac os" in ua or "macintosh" in ua:
        return "macOS"
    if "iphone" in ua or "ipad" in ua:
        return "iOS"
    if "android" in ua:
        return "Android"
    if "linux" in ua:
        return "Linux"
    return "Unknown"


def _referrer_domain(referrer: str) -> str:
    raw = (referrer or "").strip()
    if not raw:
        return ""
    try:
        return (urlparse(raw).hostname or "").lower()
    except Exception:
        return ""


def build_client_context(request, *, referrer: str = "") -> ClientContext:
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    ip_value = _extract_client_ip(request)
    ip_prefix = _ip_prefix(ip_value)
    device_type = _detect_device_type(user_agent)
    is_bot = device_type == AnalyticsSession.DEVICE_BOT
    return ClientContext(
        ip_hash=_digest(ip_value) if ip_value else "",
        ip_prefix=ip_prefix,
        user_agent_hash=_digest(user_agent) if user_agent else "",
        device_type=device_type,
        browser=_detect_browser(user_agent),
        os=_detect_os(user_agent),
        is_bot=is_bot,
        referrer_domain=_referrer_domain(referrer),
    )


def _default_session_key() -> str:
    return hashlib.sha1(str(timezone.now().timestamp()).encode("utf-8")).hexdigest()[:32]


def ingest_analytics_event(
    *,
    site,
    payload: dict[str, Any],
    request,
) -> tuple[AnalyticsEvent | None, dict[str, Any]]:
    event_type = payload.get("event_type") or AnalyticsEvent.TYPE_EVENT
    event_name = (payload.get("event_name") or "page_view").strip()[:120]
    path = (payload.get("path") or "").strip()[:255]
    title = (payload.get("title") or "").strip()[:255]
    referrer = (payload.get("referrer") or request.META.get("HTTP_REFERER") or "").strip()[:500]
    occurred_at = payload.get("occurred_at") or timezone.now()
    if timezone.is_naive(occurred_at):
        occurred_at = timezone.make_aware(occurred_at, timezone.get_current_timezone())

    context = build_client_context(request, referrer=referrer)
    if context.is_bot:
        return None, {"accepted": False, "reason": "bot_filtered"}

    session_key = (payload.get("session_key") or "").strip()[:64] or _default_session_key()
    session_defaults = {
        "started_at": occurred_at,
        "last_seen_at": occurred_at,
        "landing_path": path,
        "referrer": referrer,
        "referrer_domain": context.referrer_domain,
        "utm_source": (payload.get("utm_source") or "")[:120],
        "utm_medium": (payload.get("utm_medium") or "")[:120],
        "utm_campaign": (payload.get("utm_campaign") or "")[:120],
        "device_type": context.device_type,
        "browser": context.browser,
        "os": context.os,
        "ip_hash": context.ip_hash,
        "ip_prefix": context.ip_prefix,
        "user_agent_hash": context.user_agent_hash,
        "is_bot": False,
    }
    session, created = AnalyticsSession.objects.get_or_create(
        site=site,
        session_key=session_key,
        defaults=session_defaults,
    )
    if not created:
        session.last_seen_at = occurred_at
        if path:
            session.exit_path = path
            if not session.landing_path:
                session.landing_path = path
        for key in ("utm_source", "utm_medium", "utm_campaign"):
            value = (payload.get(key) or "")[:120]
            if value and not getattr(session, key):
                setattr(session, key, value)
        session.save(
            update_fields=[
                "last_seen_at",
                "exit_path",
                "landing_path",
                "utm_source",
                "utm_medium",
                "utm_campaign",
                "updated_at",
            ]
        )

    properties = payload.get("properties")
    if not isinstance(properties, dict):
        properties = {}

    event = AnalyticsEvent.objects.create(
        site=site,
        session=session,
        event_name=event_name,
        event_type=event_type,
        path=path,
        title=title,
        referrer=referrer,
        referrer_domain=context.referrer_domain,
        device_type=context.device_type,
        browser=context.browser,
        os=context.os,
        value=payload.get("value") or 0,
        is_bot=False,
        ip_hash=context.ip_hash,
        ip_prefix=context.ip_prefix,
        user_agent_hash=context.user_agent_hash,
        properties=properties,
        occurred_at=occurred_at,
    )

    session.event_count += 1
    if event_type == AnalyticsEvent.TYPE_PAGE_VIEW:
        session.page_view_count += 1
    if event_type == AnalyticsEvent.TYPE_CONVERSION:
        session.conversion_count += 1
    session.save(update_fields=["event_count", "page_view_count", "conversion_count", "updated_at"])

    return event, {"accepted": True, "session_key": session.session_key, "event_id": event.id}


def analytics_summary(
    *,
    site,
    period: str = "daily",
    days: int = 30,
    include_bots: bool = False,
) -> dict[str, Any]:
    days = max(1, min(days, 365))
    start_at = timezone.now() - timedelta(days=days)
    queryset = AnalyticsEvent.objects.filter(site=site, occurred_at__gte=start_at)
    sessions_queryset = AnalyticsSession.objects.filter(site=site, started_at__gte=start_at)
    if not include_bots:
        queryset = queryset.filter(is_bot=False)
        sessions_queryset = sessions_queryset.filter(is_bot=False)

    truncator = {
        "daily": TruncDate,
        "weekly": TruncWeek,
        "monthly": TruncMonth,
    }.get(period, TruncDate)

    trend = list(
        queryset.annotate(bucket=truncator("occurred_at"))
        .values("bucket")
        .annotate(
            events=Count("id"),
            page_views=Count("id", filter=models.Q(event_type=AnalyticsEvent.TYPE_PAGE_VIEW)),
            conversions=Count("id", filter=models.Q(event_type=AnalyticsEvent.TYPE_CONVERSION)),
            value=Sum("value"),
        )
        .order_by("bucket")
    )

    top_referrers = list(
        queryset.exclude(referrer_domain="")
        .values("referrer_domain")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )

    device_breakdown = list(
        queryset.values("device_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    browser_breakdown = list(
        queryset.values("browser")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )

    path_breakdown = list(
        queryset.exclude(path="")
        .values("path")
        .annotate(count=Count("id"))
        .order_by("-count")[:50]
    )

    summary = {
        "period": period,
        "days": days,
        "events": queryset.count(),
        "page_views": queryset.filter(event_type=AnalyticsEvent.TYPE_PAGE_VIEW).count(),
        "conversions": queryset.filter(event_type=AnalyticsEvent.TYPE_CONVERSION).count(),
        "funnel_events": queryset.filter(event_type=AnalyticsEvent.TYPE_FUNNEL).count(),
        "sessions": sessions_queryset.count(),
        "total_value": str(queryset.aggregate(total=Sum("value")).get("total") or 0),
    }

    return {
        "summary": summary,
        "trend": trend,
        "referrers": top_referrers,
        "devices": device_breakdown,
        "browsers": browser_breakdown,
        "paths": path_breakdown,
    }


def analytics_funnel(
    *,
    site,
    steps: list[str],
    days: int = 30,
) -> dict[str, Any]:
    days = max(1, min(days, 365))
    start_at = timezone.now() - timedelta(days=days)
    queryset = AnalyticsEvent.objects.filter(
        site=site,
        occurred_at__gte=start_at,
        event_name__in=steps,
        is_bot=False,
    ).select_related("session")

    per_step_sessions: dict[str, set[str]] = defaultdict(set)
    for event in queryset.only("event_name", "session__session_key"):
        if not event.session_id:
            continue
        per_step_sessions[event.event_name].add(event.session.session_key)

    rows: list[dict[str, Any]] = []
    baseline = None
    for step in steps:
        count = len(per_step_sessions.get(step, set()))
        if baseline is None:
            baseline = max(count, 1)
        rows.append(
            {
                "step": step,
                "sessions": count,
                "conversion_rate": round((count / baseline) * 100, 2),
            }
        )
    return {"days": days, "steps": rows}


def run_analytics_rollups(*, days_back: int = 2) -> dict[str, int]:
    days_back = max(1, min(int(days_back), 30))
    start_day = (timezone.now() - timedelta(days=days_back)).date()

    event_rows = (
        AnalyticsEvent.objects.filter(occurred_at__date__gte=start_day, is_bot=False)
        .annotate(day=TruncDate("occurred_at"))
        .values("site_id", "day")
        .annotate(
            events=Count("id"),
            page_views=Count("id", filter=models.Q(event_type=AnalyticsEvent.TYPE_PAGE_VIEW)),
            conversions=Count("id", filter=models.Q(event_type=AnalyticsEvent.TYPE_CONVERSION)),
            total_value=Sum("value"),
        )
    )
    session_rows = (
        AnalyticsSession.objects.filter(started_at__date__gte=start_day, is_bot=False)
        .annotate(day=TruncDate("started_at"))
        .values("site_id", "day")
        .annotate(sessions=Count("id"))
    )

    session_map: dict[tuple[int, Any], int] = {
        (int(row["site_id"]), row["day"]): int(row["sessions"] or 0)
        for row in session_rows
        if row.get("day") is not None
    }

    updated = 0
    for row in event_rows:
        day = row.get("day")
        site_id = int(row.get("site_id") or 0)
        if site_id <= 0 or day is None:
            continue
        defaults = {
            "events": int(row.get("events") or 0),
            "page_views": int(row.get("page_views") or 0),
            "conversions": int(row.get("conversions") or 0),
            "sessions": int(session_map.get((site_id, day), 0)),
            "total_value": row.get("total_value") or 0,
            "metadata": {"source": "scheduler.rollup"},
        }
        AnalyticsRollup.objects.update_or_create(
            site_id=site_id,
            period=AnalyticsRollup.PERIOD_DAILY,
            period_date=day,
            defaults=defaults,
        )
        updated += 1
    return {"days_back": days_back, "updated": updated}


__all__ = [
    "analytics_funnel",
    "analytics_summary",
    "build_client_context",
    "disconnect_search_console",
    "ingest_analytics_event",
    "list_search_console_properties",
    "run_analytics_rollups",
    "run_seo_page_audit",
    "sync_search_console",
    "track_commerce_event",
]
