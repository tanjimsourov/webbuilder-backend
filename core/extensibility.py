from __future__ import annotations

import hashlib
import hmac
import secrets

from django.utils import timezone

from core.models import AppInstallation, AppRegistration


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def install_app(
    *,
    app: AppRegistration,
    installed_by,
    workspace=None,
    site=None,
    scopes: list[str] | None = None,
    config: dict | None = None,
) -> AppInstallation:
    callback_secret = secrets.token_hex(24)
    defaults = {
        "installed_by": installed_by if getattr(installed_by, "is_authenticated", False) else None,
        "status": AppInstallation.STATUS_INSTALLED,
        "installed_at": timezone.now(),
        "uninstalled_at": None,
        "granted_scopes": scopes or [],
        "callback_secret_hash": _hash_secret(callback_secret),
        "config": config or {},
    }
    installation, _ = AppInstallation.objects.update_or_create(
        app=app,
        workspace=workspace,
        site=site,
        defaults=defaults,
    )
    installation.metadata = {**(installation.metadata or {}), "callback_secret": callback_secret}
    installation.save(update_fields=["metadata", "updated_at"])
    return installation


def uninstall_app(installation: AppInstallation) -> AppInstallation:
    installation.status = AppInstallation.STATUS_UNINSTALLED
    installation.uninstalled_at = timezone.now()
    installation.save(update_fields=["status", "uninstalled_at", "updated_at"])
    return installation


def verify_signed_callback(installation: AppInstallation, payload: bytes, signature: str) -> bool:
    if not signature or not installation.callback_secret_hash:
        return False
    callback_secret = str((installation.metadata or {}).get("callback_secret") or "")
    if not callback_secret:
        return False
    expected = hmac.new(callback_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
