from __future__ import annotations

import hashlib

from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from core.models import PersonalAPIKey


class PersonalAPIKeyAuthentication(authentication.BaseAuthentication):
    header_name = "HTTP_X_API_KEY"
    bearer_prefix = "Bearer "

    def _extract_key(self, request) -> str:
        direct = (request.META.get(self.header_name) or "").strip()
        if direct:
            return direct
        auth_header = (request.META.get("HTTP_AUTHORIZATION") or "").strip()
        if auth_header.startswith(self.bearer_prefix):
            token = auth_header[len(self.bearer_prefix) :].strip()
            if token.startswith("wbk_"):
                return token
        return ""

    def authenticate(self, request):
        raw_key = self._extract_key(request)
        if not raw_key:
            return None
        if not raw_key.startswith("wbk_"):
            return None
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        key = (
            PersonalAPIKey.objects.select_related("user")
            .filter(
                key_hash=key_hash,
                revoked_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        if key is None:
            raise AuthenticationFailed("Invalid API key.")
        if key.expires_at and key.expires_at <= timezone.now():
            raise AuthenticationFailed("API key expired.")
        if not key.user.is_active:
            raise AuthenticationFailed("User is inactive.")

        key.last_used_at = timezone.now()
        key.last_used_ip = (request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "").split(
            ","
        )[0].strip() or None
        key.last_used_user_agent = (request.META.get("HTTP_USER_AGENT", "") or "")[:500]
        key.save(update_fields=["last_used_at", "last_used_ip", "last_used_user_agent", "updated_at"])
        request.auth_api_key = key
        return (key.user, key)
