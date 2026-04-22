from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import SecurityToken, UserSession

User = get_user_model()


def hash_security_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_security_token(
    *,
    user: User,
    purpose: str,
    ttl_seconds: int,
    metadata: dict[str, Any] | None = None,
    session: UserSession | None = None,
    request=None,
) -> tuple[str, SecurityToken]:
    raw_token = secrets.token_urlsafe(48)
    record = SecurityToken.objects.create(
        user=user,
        session=session,
        purpose=purpose,
        token_hash=hash_security_token(raw_token),
        expires_at=timezone.now() + timedelta(seconds=max(60, int(ttl_seconds))),
        issued_ip=(
            (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(",")[0].strip()
            if request
            else None
        )
        or None,
        issued_user_agent=((request.META.get("HTTP_USER_AGENT", "") if request else "") or "")[:500],
        metadata=metadata or {},
    )
    return raw_token, record


def consume_security_token(*, raw_token: str, purpose: str) -> SecurityToken | None:
    token_hash = hash_security_token(raw_token)
    token = (
        SecurityToken.objects.select_related("user", "session")
        .filter(
            token_hash=token_hash,
            purpose=purpose,
            revoked_at__isnull=True,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if token is None:
        return None
    token.used_at = timezone.now()
    token.save(update_fields=["used_at", "updated_at"])
    return token


def rotate_refresh_token(
    *,
    raw_token: str,
    ttl_seconds: int = 60 * 60 * 24 * 30,
    request=None,
) -> tuple[User, str] | None:
    token_hash = hash_security_token(raw_token)
    existing = (
        SecurityToken.objects.select_related("user", "session")
        .filter(
            token_hash=token_hash,
            purpose=SecurityToken.PURPOSE_REFRESH,
            revoked_at__isnull=True,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if existing is None:
        return None

    existing.used_at = timezone.now()
    existing.revoked_at = timezone.now()
    existing.save(update_fields=["used_at", "revoked_at", "updated_at"])

    new_raw, new_record = issue_security_token(
        user=existing.user,
        purpose=SecurityToken.PURPOSE_REFRESH,
        ttl_seconds=ttl_seconds,
        session=existing.session,
        request=request,
        metadata={"rotated_from": existing.id, "session_id": existing.session_id},
    )
    if existing.session_id:
        UserSession.objects.filter(pk=existing.session_id, revoked_at__isnull=True).update(
            refresh_token_hash=new_record.token_hash,
            updated_at=timezone.now(),
        )
    return existing.user, new_raw


def revoke_refresh_token(raw_token: str) -> bool:
    token_hash = hash_security_token(raw_token)
    token = (
        SecurityToken.objects.filter(
            token_hash=token_hash,
            purpose=SecurityToken.PURPOSE_REFRESH,
            revoked_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if token is None:
        return False
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at", "updated_at"])
    return True


def revoke_all_refresh_tokens(user: User) -> int:
    return SecurityToken.objects.filter(
        user=user,
        purpose=SecurityToken.PURPOSE_REFRESH,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now(), updated_at=timezone.now())
