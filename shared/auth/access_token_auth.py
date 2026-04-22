from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed

from core.models import UserSecurityState


class SignedAccessTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"
    salt = "wb.auth.access.v1"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header:
            return None
        if not auth_header.startswith(f"{self.keyword} "):
            return None
        token = auth_header[len(self.keyword) :].strip()
        if not token or token.startswith("wbk_"):
            return None
        try:
            payload = signing.loads(token, salt=self.salt)
        except signing.BadSignature as exc:
            raise AuthenticationFailed("Invalid access token.") from exc

        user_id = payload.get("sub")
        expires_at = int(payload.get("exp", 0))
        token_version = int(payload.get("ver", 1))
        if not user_id:
            raise AuthenticationFailed("Invalid access token payload.")
        if expires_at <= int(timezone.now().timestamp()):
            raise AuthenticationFailed("Access token expired.")

        User = get_user_model()
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            raise AuthenticationFailed("User not found.")

        state, _ = UserSecurityState.objects.get_or_create(user=user)
        if token_version != int(state.access_token_version or 1):
            raise AuthenticationFailed("Access token revoked.")
        return (user, None)
