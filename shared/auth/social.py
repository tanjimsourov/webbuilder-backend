from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SocialIdentity:
    provider: str
    provider_user_id: str
    email: str
    email_verified: bool = False
    display_name: str = ""
    avatar_url: str = ""


class SocialProviderAdapter:
    provider: str = "unknown"

    def verify(self, *, access_token: str) -> SocialIdentity:  # pragma: no cover - interface
        raise NotImplementedError


class SocialProviderRegistry:
    def __init__(self):
        self._providers: dict[str, SocialProviderAdapter] = {}

    def register(self, adapter: SocialProviderAdapter) -> None:
        self._providers[adapter.provider] = adapter

    def get(self, provider: str) -> SocialProviderAdapter | None:
        return self._providers.get((provider or "").strip().lower())


registry = SocialProviderRegistry()
