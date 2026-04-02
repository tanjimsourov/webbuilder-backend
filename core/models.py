from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models


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
    """A workspace groups sites and members together for access control."""

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

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WorkspaceMembership(TimeStampedModel):
    """Membership linking users to workspaces with roles."""

    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_EDITOR = "editor"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_VIEWER, "Viewer"),
    ]

    workspace = models.ForeignKey(Workspace, related_name="memberships", on_delete=models.CASCADE)
    user = models.ForeignKey(get_user_model(), related_name="workspace_memberships", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
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
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN)

    @property
    def can_edit_content(self) -> bool:
        return self.role in (self.ROLE_OWNER, self.ROLE_ADMIN, self.ROLE_EDITOR)

    @property
    def can_view_content(self) -> bool:
        return True


class WorkspaceInvitation(TimeStampedModel):
    """Pending invitation to join a workspace."""

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
