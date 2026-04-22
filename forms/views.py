"""Forms domain views, including headless runtime public endpoints."""

from __future__ import annotations

import re

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from builder.form_views import (  # noqa: F401
    FormViewSet,
    PublicFormView,
    generate_form_html,
    render_field_html,
)
from builder.views import (  # noqa: F401
    FormSubmissionViewSet,
    PublicFormSubmissionView,
)
from cms.models import Page
from cms.services import public_site_capabilities, resolve_public_page
from core.views import PublicRuntimeSiteMixin
from forms.models import Form, FormSubmission
from forms.serializers import PublicRuntimeFormSchemaSerializer, PublicRuntimeFormSubmitSerializer
from forms.services import (
    evaluate_form_spam,
    export_form_submissions_csv,
    queue_form_email_notifications,
    trigger_webhooks,
)
from shared.policies.access import SitePermission, has_site_permission
from shared.contracts.sanitize import sanitize_json_payload


def _validate_runtime_form_payload(form: Form, payload: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    for field in form.fields:
        field_name = str(field.get("name") or "").strip()
        if not field_name:
            continue

        label = str(field.get("label") or field_name).strip()
        value = payload.get(field_name)
        required = bool(field.get("required", False))
        field_type = str(field.get("type") or "text").strip().lower()

        if required and (value is None or str(value).strip() == ""):
            errors[field_name] = f"{label} is required."
            continue

        if value in (None, ""):
            continue

        text_value = str(value)
        if field_type == "email" and ("@" not in text_value or "." not in text_value):
            errors[field_name] = "Please enter a valid email address."
            continue

        validation = field.get("validation") if isinstance(field.get("validation"), dict) else {}
        min_length = validation.get("minLength")
        max_length = validation.get("maxLength")
        pattern = validation.get("pattern")
        if min_length is not None and len(text_value) < int(min_length):
            errors[field_name] = f"Must be at least {int(min_length)} characters."
        elif max_length is not None and len(text_value) > int(max_length):
            errors[field_name] = f"Must be at most {int(max_length)} characters."
        elif pattern:
            try:
                if not re.match(str(pattern), text_value):
                    errors[field_name] = str(validation.get("patternMessage") or "Invalid format.")
            except re.error:
                errors[field_name] = "Invalid validation pattern configuration."
    return errors


class PublicRuntimeFormSchemaView(PublicRuntimeSiteMixin, APIView):
    """Read-only public form schema endpoint for runtime rendering."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, form_slug: str):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("forms_enabled", False):
            return Response({"detail": "Forms are disabled for this site."}, status=status.HTTP_404_NOT_FOUND)

        form = get_object_or_404(Form, site=site, slug=form_slug, status=Form.STATUS_ACTIVE)
        serializer = PublicRuntimeFormSchemaSerializer(form)
        return Response({"site": {"id": site.id, "slug": site.slug}, "form": serializer.data})


class PublicRuntimeFormSubmissionView(PublicRuntimeSiteMixin, APIView):
    """Public runtime form submission endpoint with published-page linkage."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get_throttles(self):
        from builder.throttles import PublicFormThrottle

        return [PublicFormThrottle()]

    def post(self, request, form_slug: str):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("forms_enabled", False):
            return Response({"detail": "Forms are disabled for this site."}, status=status.HTTP_404_NOT_FOUND)

        form = get_object_or_404(Form, site=site, slug=form_slug, status=Form.STATUS_ACTIVE)
        serializer = PublicRuntimeFormSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = dict(serializer.validated_data["payload"] or {})
        honeypot_value = payload.pop(form.honeypot_field, None)
        if honeypot_value:
            # Quiet success for bot-style honeypot submissions.
            return Response(
                {
                    "success": True,
                    "message": form.success_message,
                    "redirect_url": form.redirect_url or None,
                }
            )

        errors = _validate_runtime_form_payload(form, payload)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        spam_result = evaluate_form_spam(
            form=form,
            payload=payload,
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
            ip_address=(request.META.get("REMOTE_ADDR") or "")[:64],
        )
        if spam_result.is_spam:
            return Response(
                {
                    "success": True,
                    "message": form.success_message,
                    "redirect_url": form.redirect_url or None,
                }
            )

        page = None
        page_path = serializer.validated_data.get("page_path") or ""
        locale_code = serializer.validated_data.get("locale") or ""
        if page_path:
            page_resolution = resolve_public_page(site, page_path, locale_code=locale_code)
            page = page_resolution.page
        if page is None:
            page = (
                site.pages.filter(status=Page.STATUS_PUBLISHED, is_homepage=True)
                .filter(Q(published_at__isnull=True) | Q(published_at__lte=timezone.now()))
                .first()
            )

        submission = FormSubmission.objects.create(
            site=site,
            page=page,
            form_name=form.slug,
            payload=sanitize_json_payload(payload),
            status=FormSubmission.STATUS_NEW,
        )
        trigger_webhooks(
            site,
            "form.submitted",
            {
                "form_id": form.id,
                "form_slug": form.slug,
                "submission_id": submission.id,
                "payload": payload,
            },
        )
        queue_form_email_notifications(form=form, submission=submission)
        return Response(
            {
                "success": True,
                "message": form.success_message,
                "redirect_url": form.redirect_url or None,
                "submission_id": submission.id,
            },
            status=status.HTTP_201_CREATED,
        )


class FormSubmissionExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, form_id: int):
        form = get_object_or_404(Form.objects.select_related("site", "site__workspace"), pk=form_id)
        if not has_site_permission(request.user, form.site, SitePermission.VIEW):
            return Response({"detail": "You don't have permission to export submissions."}, status=status.HTTP_403_FORBIDDEN)
        csv_data = export_form_submissions_csv(form=form)
        filename = f"form-{form.slug}-submissions.csv"
        response = HttpResponse(csv_data, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


__all__ = [
    "FormSubmissionViewSet",
    "FormSubmissionExportView",
    "FormViewSet",
    "PublicFormSubmissionView",
    "PublicFormView",
    "PublicRuntimeFormSchemaView",
    "PublicRuntimeFormSubmissionView",
    "generate_form_html",
    "render_field_html",
]
