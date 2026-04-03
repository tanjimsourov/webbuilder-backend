"""Serializers for the email hosting domain."""

from __future__ import annotations

import re

from rest_framework import serializers

from core.models import Site
from email_hosting.models import EmailDomain, EmailProvisioningTask, MailAlias, Mailbox

LOCAL_PART_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")


class EmailDomainSerializer(serializers.ModelSerializer):
    dns_instructions = serializers.SerializerMethodField()

    class Meta:
        model = EmailDomain
        fields = [
            "id",
            "site",
            "workspace",
            "name",
            "status",
            "verification_token",
            "verified_at",
            "mx_record",
            "spf_record",
            "dkim_record",
            "dmarc_record",
            "dns_instructions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "workspace",
            "status",
            "verification_token",
            "verified_at",
            "mx_record",
            "spf_record",
            "dkim_record",
            "dmarc_record",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value: str) -> str:
        cleaned = value.strip().lower().rstrip(".")
        if "." not in cleaned:
            raise serializers.ValidationError("Enter a fully qualified domain name.")
        return cleaned

    def validate_site(self, value: Site) -> Site:
        if value.workspace_id is None:
            raise serializers.ValidationError("Site must belong to a workspace.")
        return value

    def get_dns_instructions(self, obj: EmailDomain) -> list[dict[str, str]]:
        selector = "k1"
        return [
            {"type": "MX", "name": "@", "value": obj.mx_record},
            {"type": "TXT", "name": "@", "value": obj.spf_record},
            {"type": "TXT", "name": f"{selector}._domainkey", "value": obj.dkim_record},
            {"type": "TXT", "name": "_dmarc", "value": obj.dmarc_record},
            {
                "type": "TXT",
                "name": "_webbuilder-verify",
                "value": f"webbuilder-verify={obj.verification_token}",
            },
        ]


class MailboxSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    email_address = serializers.CharField(read_only=True)
    domain_name = serializers.CharField(source="domain.name", read_only=True)

    class Meta:
        model = Mailbox
        fields = [
            "id",
            "workspace",
            "site",
            "domain",
            "domain_name",
            "local_part",
            "password",
            "is_active",
            "quota_mb",
            "last_login",
            "user",
            "email_address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "workspace",
            "site",
            "domain_name",
            "last_login",
            "email_address",
            "created_at",
            "updated_at",
        ]

    def validate_local_part(self, value: str) -> str:
        cleaned = value.strip().lower()
        if not LOCAL_PART_RE.match(cleaned):
            raise serializers.ValidationError(
                "Mailbox local part can contain letters, numbers, dot, underscore, plus, and hyphen."
            )
        return cleaned


class MailAliasSerializer(serializers.ModelSerializer):
    destination_email = serializers.CharField(source="destination_mailbox.email_address", read_only=True)

    class Meta:
        model = MailAlias
        fields = [
            "id",
            "workspace",
            "site",
            "source_address",
            "destination_mailbox",
            "destination_email",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "workspace",
            "site",
            "destination_email",
            "created_at",
            "updated_at",
        ]

    def validate_source_address(self, value: str) -> str:
        return value.strip().lower()


class EmailProvisioningTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailProvisioningTask
        fields = [
            "id",
            "workspace",
            "task_type",
            "target_id",
            "status",
            "message",
            "payload",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class EmailDomainCreateSerializer(serializers.Serializer):
    domain_name = serializers.CharField(max_length=253)
    site_id = serializers.IntegerField()
    queue_verification = serializers.BooleanField(default=True)

    def validate_domain_name(self, value: str) -> str:
        cleaned = value.strip().lower().rstrip(".")
        if "." not in cleaned:
            raise serializers.ValidationError("Enter a fully qualified domain name.")
        return cleaned


class MailboxCreateSerializer(serializers.Serializer):
    domain_id = serializers.IntegerField()
    local_part = serializers.CharField(max_length=64)
    password = serializers.CharField(min_length=8)
    quota_mb = serializers.IntegerField(default=1024, min_value=64, max_value=51200)
    user_id = serializers.IntegerField(required=False, allow_null=True)
    queue_provisioning = serializers.BooleanField(default=True)

    def validate_local_part(self, value: str) -> str:
        cleaned = value.strip().lower()
        if not LOCAL_PART_RE.match(cleaned):
            raise serializers.ValidationError(
                "Mailbox local part can contain letters, numbers, dot, underscore, plus, and hyphen."
            )
        return cleaned

