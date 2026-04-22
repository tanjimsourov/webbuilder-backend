from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from core.models import UserAccount, UserSecurityState

User = get_user_model()


def _cache_key(prefix: str, *, username: str, ip: str) -> str:
    return f"auth:{prefix}:{username.lower()}:{ip}"


def _settings_int(name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def login_backoff_wait_seconds(username: str, ip: str) -> int:
    until = cache.get(_cache_key("backoff_until", username=username, ip=ip))
    if not until:
        return 0
    remaining = int((until - timezone.now()).total_seconds())
    return max(remaining, 0)


def _security_state(user: User) -> UserSecurityState:
    state, _ = UserSecurityState.objects.get_or_create(user=user)
    return state


def user_is_locked(user: User) -> tuple[bool, int]:
    state = _security_state(user)
    account = getattr(user, "account", None)
    if account and account.status == UserAccount.STATUS_LOCKED:
        if state.locked_until and state.locked_until > timezone.now():
            seconds = int((state.locked_until - timezone.now()).total_seconds())
            return True, max(seconds, 0)
        return True, _settings_int("AUTH_LOCKOUT_SECONDS", 900)
    if state.locked_until and state.locked_until > timezone.now():
        seconds = int((state.locked_until - timezone.now()).total_seconds())
        return True, max(seconds, 0)
    return False, 0


def record_failed_login(*, username: str, ip: str, user: User | None = None) -> tuple[bool, int]:
    now = timezone.now()
    max_failures = _settings_int("AUTH_MAX_FAILED_LOGIN_ATTEMPTS", 7)
    lockout_seconds = _settings_int("AUTH_LOCKOUT_SECONDS", 900)
    backoff_cap = _settings_int("AUTH_BACKOFF_MAX_SECONDS", 16)
    cache_ttl = max(lockout_seconds, 1800)

    count_key = _cache_key("fail_count", username=username, ip=ip)
    fail_count = int(cache.get(count_key) or 0) + 1
    cache.set(count_key, fail_count, timeout=cache_ttl)

    if fail_count >= 2:
        # Exponential backoff after repeated misses.
        wait_seconds = min(backoff_cap, 2 ** min(fail_count - 2, 8))
        backoff_until = now + timedelta(seconds=wait_seconds)
        cache.set(_cache_key("backoff_until", username=username, ip=ip), backoff_until, timeout=cache_ttl)

    if user is None:
        user = User.objects.filter(username=username).first()

    locked = False
    retry_after = 0
    if user is not None:
        state = _security_state(user)
        state.failed_login_count = int(state.failed_login_count or 0) + 1
        state.last_failed_login_at = now
        if state.failed_login_count >= max_failures:
            state.locked_until = now + timedelta(seconds=lockout_seconds)
            locked = True
            retry_after = lockout_seconds
        state.save(
            update_fields=[
                "failed_login_count",
                "last_failed_login_at",
                "locked_until",
                "updated_at",
            ]
        )
        if locked:
            account = getattr(user, "account", None)
            if account and account.status != UserAccount.STATUS_LOCKED:
                account.status = UserAccount.STATUS_LOCKED
                account.save(update_fields=["status", "updated_at"])
            return True, retry_after

    return False, login_backoff_wait_seconds(username, ip)


def clear_login_failures(*, username: str, ip: str, user: User | None = None) -> None:
    cache.delete(_cache_key("fail_count", username=username, ip=ip))
    cache.delete(_cache_key("backoff_until", username=username, ip=ip))

    if user is not None:
        state = _security_state(user)
        state.failed_login_count = 0
        state.locked_until = None
        state.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
        account = getattr(user, "account", None)
        if account and account.status == UserAccount.STATUS_LOCKED:
            account.status = UserAccount.STATUS_ACTIVE
            account.save(update_fields=["status", "updated_at"])
