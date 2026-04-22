from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Site(TimeStampedModel):
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    tagline = models.CharField(max_length=180, blank=True)
    domain = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    theme = models.JSONField(default=dict, blank=True)
    navigation = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    workspace = models.ForeignKey(
        "Workspace",
        related_name="sites",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            from cms.localization import ensure_site_locale  # deferred import

            localization = (self.settings or {}).get("localization") or {}
            default_locale = localization.get("default_locale") or "en"
            if not self.locales.exists():
                ensure_site_locale(self, default_locale, is_default=True)

    def __str__(self) -> str:
        return self.name

    def default_locale_code(self) -> str:
        default_locale = self.locales.filter(is_enabled=True, is_default=True).first()
        if default_locale:
            return default_locale.code
        first_enabled = self.locales.filter(is_enabled=True).order_by("code").first()
        return first_enabled.code if first_enabled else "en"

    def public_locales(self) -> list[dict[str, object]]:
        return [
            {
                "code": locale.code,
                "direction": locale.direction,
                "is_default": locale.is_default,
            }
            for locale in self.locales.filter(is_enabled=True).order_by("-is_default", "code")
        ]


class SiteLocale(TimeStampedModel):
    DIRECTION_LTR = "ltr"
    DIRECTION_RTL = "rtl"
    DIRECTION_CHOICES = [
        (DIRECTION_LTR, "Left to right"),
        (DIRECTION_RTL, "Right to left"),
    ]

    site = models.ForeignKey(Site, related_name="locales", on_delete=models.CASCADE)
    code = models.CharField(max_length=32)
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES, default=DIRECTION_LTR)
    is_default = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "code"]
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="core_unique_site_locale_code"),
            models.UniqueConstraint(
                fields=["site"],
                condition=models.Q(is_default=True),
                name="core_unique_default_locale_per_site",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.code}"


class Workspace(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        get_user_model(),
        related_name="owned_workspaces",
        on_delete=models.CASCADE,
    )
    settings = models.JSONField(default=dict, blank=True)
    is_personal = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceMembership(TimeStampedModel):
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_EDITOR = "editor"
    ROLE_AUTHOR = "author"
    ROLE_ANALYST = "analyst"
    ROLE_SUPPORT = "support"
    ROLE_BILLING_MANAGER = "billing_manager"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_AUTHOR, "Author"),
        (ROLE_ANALYST, "Analyst"),
        (ROLE_SUPPORT, "Support"),
        (ROLE_BILLING_MANAGER, "Billing manager"),
        (ROLE_VIEWER, "Viewer"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="memberships", on_delete=models.CASCADE)
    user = models.ForeignKey(get_user_model(), related_name="workspace_memberships", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    invited_by = models.ForeignKey(
        get_user_model(),
        related_name="sent_invitations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["role", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="core_unique_workspace_user"),
        ]

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.user.username} ({self.role})"

    @property
    def can_manage_members(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_SUPPORT)

    @property
    def can_manage_billing(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_BILLING_MANAGER)

    @property
    def can_edit_content(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_EDITOR, self.ROLE_AUTHOR)

    @property
    def can_view_analytics(self) -> bool:
        return self.role in (
            self.ROLE_OWNER,
            self.ROLE_ADMIN,
            self.ROLE_EDITOR,
            self.ROLE_AUTHOR,
            self.ROLE_ANALYST,
        )

    @property
    def can_view_content(self) -> bool:
        return self.status == self.STATUS_ACTIVE


class SiteMembership(TimeStampedModel):
    ROLE_SITE_OWNER = "site_owner"
    ROLE_EDITOR = "editor"
    ROLE_AUTHOR = "author"
    ROLE_ANALYST = "analyst"
    ROLE_SUPPORT = "support"
    ROLE_BILLING_MANAGER = "billing_manager"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_SITE_OWNER, "Site owner"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_AUTHOR, "Author"),
        (ROLE_ANALYST, "Analyst"),
        (ROLE_SUPPORT, "Support"),
        (ROLE_BILLING_MANAGER, "Billing manager"),
        (ROLE_VIEWER, "Viewer"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    site = models.ForeignKey(Site, related_name="memberships", on_delete=models.CASCADE)
    user = models.ForeignKey(get_user_model(), related_name="site_memberships", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    granted_by = models.ForeignKey(
        get_user_model(),
        related_name="granted_site_memberships",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["site__name", "role", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["site", "user"], name="core_unique_site_user"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.user.username} ({self.role})"

    @property
    def can_manage_site(self) -> bool:
        return self.role in (self.ROLE_SITE_OWNER, self.ROLE_SUPPORT)

    @property
    def can_edit_content(self) -> bool:
        return self.role in (self.ROLE_SITE_OWNER, self.ROLE_EDITOR, self.ROLE_AUTHOR)

    @property
    def can_view_analytics(self) -> bool:
        return self.role in (
            self.ROLE_SITE_OWNER,
            self.ROLE_EDITOR,
            self.ROLE_AUTHOR,
            self.ROLE_ANALYST,
        )

    @property
    def can_manage_billing(self) -> bool:
        return self.role in (self.ROLE_SITE_OWNER, self.ROLE_BILLING_MANAGER)


class WorkspaceInvitation(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_EXPIRED, "Expired"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="invitations", on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=WorkspaceMembership.ROLE_CHOICES,
        default=WorkspaceMembership.ROLE_EDITOR,
    )
    token = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    invited_by = models.ForeignKey(get_user_model(), related_name="workspace_invitations", on_delete=models.CASCADE)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.workspace.name}: {self.email} ({self.status})"


class UserAccount(TimeStampedModel):
    STATUS_ACTIVE = "active"
    STATUS_PENDING = "pending"
    STATUS_LOCKED = "locked"
    STATUS_SUSPENDED = "suspended"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PENDING, "Pending"),
        (STATUS_LOCKED, "Locked"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_DELETED, "Deleted"),
    ]

    user = models.OneToOneField(get_user_model(), related_name="account", on_delete=models.CASCADE)
    email = models.EmailField(unique=True, db_index=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    display_name = models.CharField(max_length=160, blank=True)
    avatar_url = models.URLField(max_length=600, blank=True)
    profile_bio = models.TextField(blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=32, default="en")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_support_agent = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)
    data_processing_consent_at = models.DateTimeField(null=True, blank=True)
    marketing_opt_in = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["user__username"]
        indexes = [
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"Account: {self.user.username}"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)


class UserSecurityState(TimeStampedModel):
    user = models.OneToOneField(get_user_model(), related_name="security_state", on_delete=models.CASCADE)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    failed_login_count = models.PositiveIntegerField(default=0)
    last_failed_login_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_password_change_at = models.DateTimeField(null=True, blank=True)
    last_mfa_at = models.DateTimeField(null=True, blank=True)
    access_token_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"Security state: {self.user.username}"


class UserSession(TimeStampedModel):
    AUTH_SESSION = "session"
    AUTH_ACCESS_TOKEN = "access_token"
    AUTH_API_KEY = "api_key"
    AUTH_IMPERSONATION = "impersonation"
    AUTH_METHOD_CHOICES = [
        (AUTH_SESSION, "Session cookie"),
        (AUTH_ACCESS_TOKEN, "Access token"),
        (AUTH_API_KEY, "API key"),
        (AUTH_IMPERSONATION, "Impersonation"),
    ]

    user = models.ForeignKey(get_user_model(), related_name="user_sessions", on_delete=models.CASCADE)
    session_key = models.CharField(max_length=120, db_index=True)
    auth_method = models.CharField(max_length=20, choices=AUTH_METHOD_CHOICES, default=AUTH_SESSION)
    device_id = models.CharField(max_length=64, blank=True)
    device_name = models.CharField(max_length=180, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True)
    refresh_token_hash = models.CharField(max_length=128, blank=True, db_index=True)
    impersonated_by = models.ForeignKey(
        get_user_model(),
        related_name="impersonated_user_sessions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    last_seen_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "revoked_at", "last_seen_at"]),
            models.Index(fields=["session_key", "revoked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}: {self.auth_method}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class SecurityToken(TimeStampedModel):
    PURPOSE_EMAIL_VERIFY = "email_verify"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_REFRESH = "refresh"
    PURPOSE_MFA_CHALLENGE = "mfa_challenge"
    PURPOSE_CHOICES = [
        (PURPOSE_EMAIL_VERIFY, "Email verification"),
        (PURPOSE_PASSWORD_RESET, "Password reset"),
        (PURPOSE_REFRESH, "Refresh token"),
        (PURPOSE_MFA_CHALLENGE, "MFA challenge"),
    ]

    user = models.ForeignKey(get_user_model(), related_name="security_tokens", on_delete=models.CASCADE)
    session = models.ForeignKey(
        UserSession,
        related_name="security_tokens",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    purpose = models.CharField(max_length=32, choices=PURPOSE_CHOICES)
    token_hash = models.CharField(max_length=128, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    issued_ip = models.GenericIPAddressField(blank=True, null=True)
    issued_user_agent = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["purpose", "expires_at"]),
            models.Index(fields=["user", "purpose", "created_at"]),
            models.Index(fields=["session", "purpose", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} [{self.purpose}]"


class MFATOTPDevice(TimeStampedModel):
    user = models.OneToOneField(get_user_model(), related_name="mfa_totp_device", on_delete=models.CASCADE)
    secret = models.CharField(max_length=128)
    is_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"TOTP: {self.user.username}"


class MFARecoveryCode(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), related_name="mfa_recovery_codes", on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=128, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "used_at"]),
        ]

    def __str__(self) -> str:
        return f"Recovery code: {self.user.username}"


class SecurityAuditLog(TimeStampedModel):
    actor = models.ForeignKey(
        get_user_model(),
        related_name="security_audit_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=120, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    success = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def __str__(self) -> str:
        actor = self.actor.username if self.actor_id else "anonymous"
        return f"{self.action} ({actor})"


class PersonalAPIKey(TimeStampedModel):
    user = models.ForeignKey(get_user_model(), related_name="personal_api_keys", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    key_prefix = models.CharField(max_length=16)
    key_hash = models.CharField(max_length=128, db_index=True)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(blank=True, null=True)
    last_used_user_agent = models.CharField(max_length=500, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["key_prefix", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}: {self.name}"


class ImpersonationAudit(TimeStampedModel):
    actor = models.ForeignKey(
        get_user_model(),
        related_name="impersonations_started",
        on_delete=models.CASCADE,
    )
    target = models.ForeignKey(
        get_user_model(),
        related_name="impersonations_received",
        on_delete=models.CASCADE,
    )
    reason = models.CharField(max_length=280, blank=True)
    session_key = models.CharField(max_length=120, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["actor", "started_at"]),
            models.Index(fields=["target", "started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor.username} -> {self.target.username}"


class RBACPermission(TimeStampedModel):
    SCOPE_PLATFORM = "platform"
    SCOPE_WORKSPACE = "workspace"
    SCOPE_SITE = "site"
    SCOPE_CHOICES = [
        (SCOPE_PLATFORM, "Platform"),
        (SCOPE_WORKSPACE, "Workspace"),
        (SCOPE_SITE, "Site"),
    ]

    code = models.CharField(max_length=120, unique=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    description = models.CharField(max_length=280, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["scope", "code"]

    def __str__(self) -> str:
        return self.code


class RBACRole(TimeStampedModel):
    SCOPE_PLATFORM = "platform"
    SCOPE_WORKSPACE = "workspace"
    SCOPE_SITE = "site"
    SCOPE_CHOICES = [
        (SCOPE_PLATFORM, "Platform"),
        (SCOPE_WORKSPACE, "Workspace"),
        (SCOPE_SITE, "Site"),
    ]

    code = models.CharField(max_length=80, unique=True)
    label = models.CharField(max_length=140)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES)
    description = models.CharField(max_length=280, blank=True)
    is_system = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["scope", "code"]

    def __str__(self) -> str:
        return self.code


class RBACRolePermission(TimeStampedModel):
    role = models.ForeignKey(RBACRole, related_name="role_permissions", on_delete=models.CASCADE)
    permission = models.ForeignKey(RBACPermission, related_name="permission_roles", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="core_unique_role_permission"),
        ]
        ordering = ["role__code", "permission__code"]

    def __str__(self) -> str:
        return f"{self.role.code} -> {self.permission.code}"


class ConsentRecord(TimeStampedModel):
    CONSENT_PRIVACY = "privacy"
    CONSENT_TERMS = "terms"
    CONSENT_COOKIES = "cookies"
    CONSENT_MARKETING = "marketing"
    CONSENT_ANALYTICS = "analytics"
    CONSENT_CHOICES = [
        (CONSENT_PRIVACY, "Privacy"),
        (CONSENT_TERMS, "Terms"),
        (CONSENT_COOKIES, "Cookie policy"),
        (CONSENT_MARKETING, "Marketing"),
        (CONSENT_ANALYTICS, "Analytics"),
    ]

    STATUS_GRANTED = "granted"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_GRANTED, "Granted"),
        (STATUS_REVOKED, "Revoked"),
    ]

    user = models.ForeignKey(get_user_model(), related_name="consent_records", on_delete=models.CASCADE)
    workspace = models.ForeignKey(
        Workspace,
        related_name="consent_records",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="consent_records", on_delete=models.SET_NULL, null=True, blank=True)
    consent_type = models.CharField(max_length=24, choices=CONSENT_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_GRANTED)
    policy_version = models.CharField(max_length=40, default="1")
    source = models.CharField(max_length=80, blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "consent_type", "created_at"]),
            models.Index(fields=["workspace", "consent_type", "created_at"]),
            models.Index(fields=["site", "consent_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.consent_type}:{self.status}"


class DataExportJob(TimeStampedModel):
    STATUS_QUEUED = "queued"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    FORMAT_JSON = "json"
    FORMAT_CHOICES = [
        (FORMAT_JSON, "JSON"),
    ]

    requested_by = models.ForeignKey(
        get_user_model(),
        related_name="requested_data_exports",
        on_delete=models.CASCADE,
    )
    target_user = models.ForeignKey(
        get_user_model(),
        related_name="data_export_jobs",
        on_delete=models.CASCADE,
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name="data_export_jobs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="data_export_jobs", on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    export_format = models.CharField(max_length=16, choices=FORMAT_CHOICES, default=FORMAT_JSON)
    result_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    queued_job_id = models.CharField(max_length=64, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_user", "status", "created_at"]),
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"export:{self.target_user_id}:{self.status}"


class DataDeletionJob(TimeStampedModel):
    STATUS_REQUESTED = "requested"
    STATUS_APPROVED = "approved"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_FAILED, "Failed"),
    ]

    requested_by = models.ForeignKey(
        get_user_model(),
        related_name="requested_data_deletions",
        on_delete=models.CASCADE,
    )
    target_user = models.ForeignKey(
        get_user_model(),
        related_name="data_deletion_jobs",
        on_delete=models.CASCADE,
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name="data_deletion_jobs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(Site, related_name="data_deletion_jobs", on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    reason = models.CharField(max_length=280, blank=True)
    approved_by = models.ForeignKey(
        get_user_model(),
        related_name="approved_data_deletions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    queued_job_id = models.CharField(max_length=64, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_user", "status", "created_at"]),
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"deletion:{self.target_user_id}:{self.status}"


class AppScope(TimeStampedModel):
    code = models.CharField(max_length=120, unique=True)
    description = models.CharField(max_length=280, blank=True)
    is_sensitive = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class AppRegistration(TimeStampedModel):
    slug = models.SlugField(max_length=120, unique=True)
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    homepage_url = models.URLField(max_length=500, blank=True)
    callback_url = models.URLField(max_length=500, blank=True)
    webhook_url = models.URLField(max_length=500, blank=True)
    signing_secret_hash = models.CharField(max_length=128, blank=True)
    is_active = models.BooleanField(default=True)
    requires_review = models.BooleanField(default=True)
    current_version = models.CharField(max_length=40, default="1.0.0")
    metadata = models.JSONField(default=dict, blank=True)
    scopes = models.ManyToManyField(AppScope, through="AppRegistrationScope", related_name="apps")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.slug


class AppRegistrationScope(TimeStampedModel):
    app = models.ForeignKey(AppRegistration, related_name="app_scopes", on_delete=models.CASCADE)
    scope = models.ForeignKey(AppScope, related_name="scope_apps", on_delete=models.CASCADE)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ["app__slug", "scope__code"]
        constraints = [
            models.UniqueConstraint(fields=["app", "scope"], name="core_unique_app_scope"),
        ]

    def __str__(self) -> str:
        return f"{self.app.slug}:{self.scope.code}"


class AppInstallation(TimeStampedModel):
    STATUS_INSTALLED = "installed"
    STATUS_SUSPENDED = "suspended"
    STATUS_UNINSTALLED = "uninstalled"
    STATUS_CHOICES = [
        (STATUS_INSTALLED, "Installed"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_UNINSTALLED, "Uninstalled"),
    ]

    app = models.ForeignKey(AppRegistration, related_name="installations", on_delete=models.CASCADE)
    workspace = models.ForeignKey(
        Workspace,
        related_name="app_installations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="app_installations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    installed_by = models.ForeignKey(
        get_user_model(),
        related_name="installed_apps",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INSTALLED)
    installed_at = models.DateTimeField(default=timezone.now)
    uninstalled_at = models.DateTimeField(null=True, blank=True)
    granted_scopes = models.JSONField(default=list, blank=True)
    callback_secret_hash = models.CharField(max_length=128, blank=True)
    config = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["app", "workspace"],
                condition=models.Q(workspace__isnull=False),
                name="core_unique_workspace_app_installation",
            ),
            models.UniqueConstraint(
                fields=["app", "site"],
                condition=models.Q(site__isnull=False),
                name="core_unique_site_app_installation",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status", "created_at"]),
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        scope = f"workspace:{self.workspace_id}" if self.workspace_id else f"site:{self.site_id}"
        return f"{self.app.slug}@{scope}"


class FeatureFlag(TimeStampedModel):
    SCOPE_GLOBAL = "global"
    SCOPE_WORKSPACE = "workspace"
    SCOPE_SITE = "site"
    SCOPE_CHOICES = [
        (SCOPE_GLOBAL, "Global"),
        (SCOPE_WORKSPACE, "Workspace"),
        (SCOPE_SITE, "Site"),
    ]

    key = models.CharField(max_length=140, unique=True)
    description = models.CharField(max_length=280, blank=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default=SCOPE_GLOBAL)
    enabled_by_default = models.BooleanField(default=False)
    rollout_percentage = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key


class FeatureFlagAssignment(TimeStampedModel):
    flag = models.ForeignKey(FeatureFlag, related_name="assignments", on_delete=models.CASCADE)
    workspace = models.ForeignKey(
        Workspace,
        related_name="feature_flag_assignments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    site = models.ForeignKey(
        Site,
        related_name="feature_flag_assignments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        get_user_model(),
        related_name="feature_flag_assignments",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    enabled = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["flag", "workspace"]),
            models.Index(fields=["flag", "site"]),
            models.Index(fields=["flag", "user"]),
        ]

    def __str__(self) -> str:
        return f"{self.flag.key}:{self.enabled}"


class DataRetentionPolicy(TimeStampedModel):
    LOG_SECURITY_AUDIT = "security_audit"
    LOG_WEBHOOK_DELIVERY = "webhook_delivery"
    LOG_ANALYTICS = "analytics"
    LOG_AI = "ai"
    LOG_CHOICES = [
        (LOG_SECURITY_AUDIT, "Security audit"),
        (LOG_WEBHOOK_DELIVERY, "Webhook delivery"),
        (LOG_ANALYTICS, "Analytics"),
        (LOG_AI, "AI"),
    ]

    log_type = models.CharField(max_length=40, choices=LOG_CHOICES, unique=True)
    retention_days = models.PositiveIntegerField(default=90)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["log_type"]

    def __str__(self) -> str:
        return f"{self.log_type}:{self.retention_days}d"
