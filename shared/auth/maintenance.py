from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.models import SecurityToken, UserSession


def cleanup_security_tokens(*, retention_days: int = 30) -> dict[str, int]:
    retention_days = max(1, min(int(retention_days), 365))
    now = timezone.now()
    cutoff = now - timedelta(days=retention_days)

    expired_or_used = SecurityToken.objects.filter(
        Q(expires_at__lt=now) | Q(used_at__isnull=False, used_at__lt=cutoff) | Q(revoked_at__isnull=False, revoked_at__lt=cutoff)
    )
    deleted_tokens = expired_or_used.delete()[0]

    revoked_sessions = UserSession.objects.filter(
        revoked_at__isnull=False,
        revoked_at__lt=cutoff,
    )
    deleted_sessions = revoked_sessions.delete()[0]

    return {
        "retention_days": retention_days,
        "deleted_tokens": int(deleted_tokens),
        "deleted_sessions": int(deleted_sessions),
    }
