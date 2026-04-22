from __future__ import annotations

import hashlib
import uuid
from typing import Any

from django.utils import timezone

from core.models import SecurityToken, UserSession


def _client_ip(request) -> str:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _device_name(user_agent: str) -> str:
    value = (user_agent or "").strip()
    if not value:
        return "Unknown device"
    return value[:180]


def _device_id(user, request) -> str:
    base = f"{user.id}:{request.META.get('HTTP_USER_AGENT', '')}:{_client_ip(request)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def _ensure_session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key or ""


def start_user_session(
    *,
    request,
    user,
    auth_method: str = UserSession.AUTH_SESSION,
    refresh_token_hash: str = "",
    impersonated_by=None,
    metadata: dict[str, Any] | None = None,
) -> UserSession:
    session_key = _ensure_session_key(request)
    record = UserSession.objects.create(
        user=user,
        session_key=session_key or uuid.uuid4().hex,
        auth_method=auth_method,
        device_id=_device_id(user, request),
        device_name=_device_name(request.META.get("HTTP_USER_AGENT", "")),
        ip_address=_client_ip(request) or None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:500],
        refresh_token_hash=(refresh_token_hash or "")[:128],
        impersonated_by=impersonated_by,
        last_seen_at=timezone.now(),
        metadata=metadata or {},
    )
    request.session["active_user_session_id"] = record.id
    request.session.modified = True
    return record


def touch_user_session(request) -> None:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return
    session_id = request.session.get("active_user_session_id")
    if not session_id:
        return
    UserSession.objects.filter(
        id=session_id,
        user=user,
        revoked_at__isnull=True,
    ).update(
        last_seen_at=timezone.now(),
        ip_address=_client_ip(request) or None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:500],
        updated_at=timezone.now(),
    )


def active_sessions_for_user(user):
    return UserSession.objects.filter(user=user, revoked_at__isnull=True).order_by("-last_seen_at", "-created_at")


def revoke_session(*, user, session_id: int) -> bool:
    session = UserSession.objects.filter(
        id=session_id,
        user=user,
        revoked_at__isnull=True,
    ).first()
    if session is None:
        return False
    session.revoked_at = timezone.now()
    session.save(update_fields=["revoked_at", "updated_at"])
    SecurityToken.objects.filter(
        user=user,
        session=session,
        purpose=SecurityToken.PURPOSE_REFRESH,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now(), updated_at=timezone.now())
    return True


def revoke_other_sessions(*, user, keep_session_id: int | None = None) -> int:
    queryset = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if keep_session_id:
        queryset = queryset.exclude(id=keep_session_id)
    session_ids = list(queryset.values_list("id", flat=True))
    count = queryset.update(revoked_at=timezone.now(), updated_at=timezone.now())
    if session_ids:
        SecurityToken.objects.filter(
            user=user,
            session_id__in=session_ids,
            purpose=SecurityToken.PURPOSE_REFRESH,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now(), updated_at=timezone.now())
    return count
