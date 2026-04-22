from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.http import HttpRequest

from core.models import SecurityAuditLog

User = get_user_model()


def _safe_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(value or {})
    for key in list(metadata.keys()):
        lowered = str(key).lower()
        if any(marker in lowered for marker in ("password", "secret", "token", "api_key", "authorization", "cookie")):
            metadata[key] = "[REDACTED]"
    return metadata


def _client_ip(request: HttpRequest | None) -> str:
    if request is None:
        return ""
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def log_security_event(
    action: str,
    *,
    request: HttpRequest | None = None,
    actor: User | None = None,
    target_type: str = "",
    target_id: str = "",
    success: bool = True,
    metadata: dict[str, Any] | None = None,
) -> None:
    SecurityAuditLog.objects.create(
        actor=actor,
        action=str(action or "").strip()[:64] or "unknown",
        target_type=str(target_type or "").strip()[:80],
        target_id=str(target_id or "").strip()[:120],
        ip_address=_client_ip(request)[:64],
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:500] if request else ""),
        request_id=(getattr(request, "request_id", "")[:128] if request else ""),
        success=bool(success),
        metadata=_safe_metadata(metadata),
    )

