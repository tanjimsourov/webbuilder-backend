"""
Custom throttle classes for rate limiting public endpoints.
"""

from rest_framework.throttling import SimpleRateThrottle


class PublicFormThrottle(SimpleRateThrottle):
    """Rate limit for public form submissions."""
    scope = "public_form"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None  # No throttling for authenticated users
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class PublicCommentThrottle(SimpleRateThrottle):
    """Rate limit for public comment submissions."""
    scope = "public_comment"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class PublicCheckoutThrottle(SimpleRateThrottle):
    """Rate limit for public checkout operations."""
    scope = "public_checkout"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class WebhookThrottle(SimpleRateThrottle):
    """Rate limit for webhook endpoints."""
    scope = "webhook"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
