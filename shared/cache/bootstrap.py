from __future__ import annotations

from django.core.cache import caches


def cache_is_healthy(alias: str = "default") -> bool:
    try:
        cache = caches[alias]
        # `RedisCache` supports `client.get_client()` but locmem does not.
        cache.set("healthcheck:ping", "1", timeout=5)
        value = cache.get("healthcheck:ping")
        return value == "1"
    except Exception:
        return False

