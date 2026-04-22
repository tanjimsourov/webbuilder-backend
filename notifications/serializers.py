"""Notifications domain serializers (transitional + native)."""

from __future__ import annotations

from rest_framework import serializers

from notifications.models import Notification, WebhookEndpoint, WebhookEndpointDelivery

from builder.serializers import (  # noqa: F401
    EmailDomainCreateSerializer,
    EmailDomainSerializer,
    EmailProvisioningTaskSerializer,
    MailAliasSerializer,
    MailboxCreateSerializer,
    MailboxSerializer,
    WebhookSerializer,
)


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = [
            "id",
            "workspace",
            "site",
            "name",
            "url",
            "subscribed_events",
            "signing_secret",
            "status",
            "max_attempts",
            "timeout_seconds",
            "headers",
            "metadata",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "signing_secret": {"write_only": True, "required": False, "allow_blank": True},
        }


class WebhookEndpointDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpointDelivery
        fields = [
            "id",
            "endpoint",
            "event",
            "payload",
            "status",
            "attempt_count",
            "max_attempts",
            "next_attempt_at",
            "last_attempt_at",
            "response_status",
            "response_body",
            "error_message",
            "response_time_ms",
            "created_at",
            "updated_at",
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient",
            "workspace",
            "site",
            "channel",
            "status",
            "subject",
            "body",
            "payload",
            "read_at",
            "delivered_at",
            "error_message",
            "created_at",
            "updated_at",
        ]


__all__ = [
    "EmailDomainCreateSerializer",
    "EmailDomainSerializer",
    "EmailProvisioningTaskSerializer",
    "MailAliasSerializer",
    "MailboxCreateSerializer",
    "MailboxSerializer",
    "NotificationSerializer",
    "WebhookEndpointDeliverySerializer",
    "WebhookEndpointSerializer",
    "WebhookSerializer",
]
