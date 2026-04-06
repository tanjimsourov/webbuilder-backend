"""Forms domain serializers, including runtime-safe public contracts."""

from __future__ import annotations

from rest_framework import serializers

from forms.models import Form

from builder.serializers import (  # noqa: F401
    FormFieldSerializer,
    FormSerializer,
    FormSubmissionSerializer,
    PublicFormSubmissionSerializer,
)


class PublicRuntimeFormSchemaSerializer(serializers.ModelSerializer):
    """Public form schema consumed by the runtime renderer."""

    class Meta:
        model = Form
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "fields",
            "submit_button_text",
            "success_message",
            "redirect_url",
            "enable_captcha",
            "honeypot_field",
            "form_class",
        ]


class PublicRuntimeFormSubmitSerializer(serializers.Serializer):
    """Payload for public runtime form submissions."""

    payload = serializers.DictField()
    page_path = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    locale = serializers.CharField(required=False, allow_blank=True)


__all__ = [
    "FormFieldSerializer",
    "FormSerializer",
    "FormSubmissionSerializer",
    "PublicFormSubmissionSerializer",
    "PublicRuntimeFormSchemaSerializer",
    "PublicRuntimeFormSubmitSerializer",
]
