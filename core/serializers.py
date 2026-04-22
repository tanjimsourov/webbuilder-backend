"""Core domain serializers."""

from __future__ import annotations

from rest_framework import serializers

from core.models import (
    AppInstallation,
    AppRegistration,
    AppRegistrationScope,
    AppScope,
    ConsentRecord,
    DataDeletionJob,
    DataExportJob,
    FeatureFlag,
    FeatureFlagAssignment,
)

from builder.serializers import (  # noqa: F401
    ChangeMemberRoleSerializer,
    CollaboratorUserSerializer,
    InviteMemberSerializer,
    SiteLocaleSerializer,
    SiteSerializer,
    WorkspaceInvitationSerializer,
    WorkspaceMembershipSerializer,
    WorkspaceSerializer,
)


class ConsentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentRecord
        fields = [
            "id",
            "user",
            "workspace",
            "site",
            "consent_type",
            "status",
            "policy_version",
            "source",
            "ip_address",
            "user_agent",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["ip_address", "user_agent", "created_at", "updated_at"]


class DataExportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataExportJob
        fields = [
            "id",
            "requested_by",
            "target_user",
            "workspace",
            "site",
            "status",
            "export_format",
            "result_payload",
            "error_message",
            "queued_job_id",
            "processed_at",
            "expires_at",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "result_payload",
            "error_message",
            "queued_job_id",
            "processed_at",
            "expires_at",
            "created_at",
            "updated_at",
        ]


class DataDeletionJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataDeletionJob
        fields = [
            "id",
            "requested_by",
            "target_user",
            "workspace",
            "site",
            "status",
            "reason",
            "approved_by",
            "queued_job_id",
            "processed_at",
            "error_message",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "approved_by",
            "queued_job_id",
            "processed_at",
            "error_message",
            "created_at",
            "updated_at",
        ]


class AppScopeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppScope
        fields = ["id", "code", "description", "is_sensitive", "metadata", "created_at", "updated_at"]


class AppRegistrationScopeSerializer(serializers.ModelSerializer):
    scope = AppScopeSerializer(read_only=True)

    class Meta:
        model = AppRegistrationScope
        fields = ["id", "scope", "required", "created_at", "updated_at"]


class AppRegistrationSerializer(serializers.ModelSerializer):
    app_scopes = AppRegistrationScopeSerializer(many=True, read_only=True)

    class Meta:
        model = AppRegistration
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "homepage_url",
            "callback_url",
            "webhook_url",
            "is_active",
            "requires_review",
            "current_version",
            "metadata",
            "app_scopes",
            "created_at",
            "updated_at",
        ]


class AppInstallationSerializer(serializers.ModelSerializer):
    app = AppRegistrationSerializer(read_only=True)
    app_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = AppInstallation
        fields = [
            "id",
            "app",
            "app_id",
            "workspace",
            "site",
            "installed_by",
            "status",
            "installed_at",
            "uninstalled_at",
            "granted_scopes",
            "config",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "installed_at", "uninstalled_at", "created_at", "updated_at"]


class FeatureFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "key",
            "description",
            "scope",
            "enabled_by_default",
            "rollout_percentage",
            "is_active",
            "metadata",
            "created_at",
            "updated_at",
        ]


class FeatureFlagAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlagAssignment
        fields = [
            "id",
            "flag",
            "workspace",
            "site",
            "user",
            "enabled",
            "metadata",
            "created_at",
            "updated_at",
        ]


__all__ = [
    "AppInstallationSerializer",
    "AppRegistrationSerializer",
    "AppRegistrationScopeSerializer",
    "AppScopeSerializer",
    "ChangeMemberRoleSerializer",
    "CollaboratorUserSerializer",
    "ConsentRecordSerializer",
    "DataDeletionJobSerializer",
    "DataExportJobSerializer",
    "FeatureFlagAssignmentSerializer",
    "FeatureFlagSerializer",
    "InviteMemberSerializer",
    "SiteLocaleSerializer",
    "SiteSerializer",
    "WorkspaceInvitationSerializer",
    "WorkspaceMembershipSerializer",
    "WorkspaceSerializer",
]
