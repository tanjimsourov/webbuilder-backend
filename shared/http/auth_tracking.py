from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import ImpersonationAudit
from shared.auth.sessions import touch_user_session


class AuthSessionTrackingMiddleware:
    """Track authenticated session activity and impersonation context."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.user_model = get_user_model()

    def __call__(self, request):
        request.impersonator = None
        impersonator_user_id = request.session.get("impersonator_user_id")
        if impersonator_user_id:
            request.impersonator = self.user_model.objects.filter(pk=impersonator_user_id).first()

        response = self.get_response(request)

        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            touch_user_session(request)
            account = getattr(user, "account", None)
            if account:
                account.last_seen_at = timezone.now()
                account.save(update_fields=["last_seen_at", "updated_at"])

        if request.session.get("impersonator_user_id") and getattr(request, "user", None):
            active_impersonation_id = request.session.get("active_impersonation_audit_id")
            if active_impersonation_id and not request.user.is_authenticated:
                ImpersonationAudit.objects.filter(pk=active_impersonation_id, ended_at__isnull=True).update(
                    ended_at=timezone.now(),
                    updated_at=timezone.now(),
                )
                request.session.pop("active_impersonation_audit_id", None)
                request.session.pop("impersonator_user_id", None)

        return response
