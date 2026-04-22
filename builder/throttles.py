"""
Custom throttle classes for rate limiting public endpoints.
"""

from rest_framework.throttling import SimpleRateThrottle
from django.conf import settings


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


class _AuthScopedThrottle(SimpleRateThrottle):
    """Shared identity strategy for auth-sensitive throttles."""

    def get_cache_key(self, request, view):
        if getattr(settings, "RUNNING_TESTS", False):
            return None
        ident_parts = [f"ip:{self.get_ident(request)}"]
        if request.user.is_authenticated:
            ident_parts.append(f"user:{request.user.pk}")
        ident = "|".join(ident_parts)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class AuthLoginThrottle(_AuthScopedThrottle):
    """Rate limit for username/password login attempts."""

    scope = "auth_login"


class AuthBootstrapThrottle(_AuthScopedThrottle):
    """Rate limit for bootstrap endpoint to reduce takeover attempts."""

    scope = "auth_bootstrap"


class AuthMagicLoginThrottle(_AuthScopedThrottle):
    """Rate limit for development magic-login endpoint."""

    scope = "auth_magic_login"


class InvitationAcceptThrottle(_AuthScopedThrottle):
    """Rate limit for invitation token acceptance attempts."""

    scope = "invitation_accept"


class AuthSessionThrottle(_AuthScopedThrottle):
    """Rate limit for auth session-management endpoints."""

    scope = "auth_session"


class PasswordResetThrottle(_AuthScopedThrottle):
    """Rate limit for password reset request/confirm endpoints."""

    scope = "password_reset"


class EmailVerificationThrottle(_AuthScopedThrottle):
    """Rate limit for email verification flows."""

    scope = "email_verification"


class AdminAPIThrottle(_AuthScopedThrottle):
    """Rate limit for privileged admin routes."""

    scope = "admin_api"
