from __future__ import annotations

from dataclasses import dataclass

from core.models import Site, SiteMembership, UserAccount, Workspace, WorkspaceMembership


class PlatformPermission:
    IMPERSONATE = "platform.impersonate"
    MANAGE_USERS = "platform.manage_users"
    MANAGE_WORKSPACES = "platform.manage_workspaces"
    READ_AUDIT = "platform.read_audit"


class WorkspacePermission:
    VIEW = "workspace.view"
    EDIT = "workspace.edit"
    MANAGE_MEMBERS = "workspace.manage_members"
    MANAGE_BILLING = "workspace.manage_billing"
    MANAGE_SITES = "workspace.manage_sites"
    SUPPORT = "workspace.support"


class SitePermission:
    VIEW = "site.view"
    EDIT = "site.edit"
    MANAGE = "site.manage"
    ANALYTICS = "site.analytics"
    BILLING = "site.billing"


WORKSPACE_PERMISSION_MATRIX: dict[str, set[str]] = {
    WorkspaceMembership.ROLE_OWNER: {
        WorkspacePermission.VIEW,
        WorkspacePermission.EDIT,
        WorkspacePermission.MANAGE_MEMBERS,
        WorkspacePermission.MANAGE_BILLING,
        WorkspacePermission.MANAGE_SITES,
        WorkspacePermission.SUPPORT,
    },
    WorkspaceMembership.ROLE_ADMIN: {
        WorkspacePermission.VIEW,
        WorkspacePermission.EDIT,
        WorkspacePermission.MANAGE_MEMBERS,
        WorkspacePermission.MANAGE_BILLING,
        WorkspacePermission.MANAGE_SITES,
    },
    WorkspaceMembership.ROLE_EDITOR: {
        WorkspacePermission.VIEW,
        WorkspacePermission.EDIT,
    },
    WorkspaceMembership.ROLE_AUTHOR: {
        WorkspacePermission.VIEW,
        WorkspacePermission.EDIT,
    },
    WorkspaceMembership.ROLE_ANALYST: {
        WorkspacePermission.VIEW,
    },
    WorkspaceMembership.ROLE_SUPPORT: {
        WorkspacePermission.VIEW,
        WorkspacePermission.SUPPORT,
        WorkspacePermission.MANAGE_MEMBERS,
    },
    WorkspaceMembership.ROLE_BILLING_MANAGER: {
        WorkspacePermission.VIEW,
        WorkspacePermission.MANAGE_BILLING,
    },
    WorkspaceMembership.ROLE_VIEWER: {
        WorkspacePermission.VIEW,
    },
}


SITE_PERMISSION_MATRIX: dict[str, set[str]] = {
    SiteMembership.ROLE_SITE_OWNER: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.MANAGE,
        SitePermission.ANALYTICS,
        SitePermission.BILLING,
    },
    SiteMembership.ROLE_EDITOR: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.ANALYTICS,
    },
    SiteMembership.ROLE_AUTHOR: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.ANALYTICS,
    },
    SiteMembership.ROLE_ANALYST: {
        SitePermission.VIEW,
        SitePermission.ANALYTICS,
    },
    SiteMembership.ROLE_SUPPORT: {
        SitePermission.VIEW,
        SitePermission.MANAGE,
    },
    SiteMembership.ROLE_BILLING_MANAGER: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.BILLING,
    },
    SiteMembership.ROLE_VIEWER: {
        SitePermission.VIEW,
    },
}


WORKSPACE_TO_SITE_PERMISSIONS: dict[str, set[str]] = {
    WorkspaceMembership.ROLE_OWNER: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.MANAGE,
        SitePermission.ANALYTICS,
        SitePermission.BILLING,
    },
    WorkspaceMembership.ROLE_ADMIN: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.MANAGE,
        SitePermission.ANALYTICS,
        SitePermission.BILLING,
    },
    WorkspaceMembership.ROLE_EDITOR: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.ANALYTICS,
    },
    WorkspaceMembership.ROLE_AUTHOR: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.ANALYTICS,
    },
    WorkspaceMembership.ROLE_ANALYST: {
        SitePermission.VIEW,
        SitePermission.ANALYTICS,
    },
    WorkspaceMembership.ROLE_SUPPORT: {
        SitePermission.VIEW,
        SitePermission.MANAGE,
    },
    WorkspaceMembership.ROLE_BILLING_MANAGER: {
        SitePermission.VIEW,
        SitePermission.EDIT,
        SitePermission.BILLING,
    },
    WorkspaceMembership.ROLE_VIEWER: {
        SitePermission.VIEW,
    },
}


@dataclass(frozen=True)
class ResolvedSiteRole:
    workspace_role: str | None
    site_role: str | None


def _account(user) -> UserAccount | None:
    return getattr(user, "account", None) if getattr(user, "is_authenticated", False) else None


def is_platform_super_admin(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and getattr(user, "is_superuser", False))


def is_support_agent(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_super_admin(user):
        return True
    account = _account(user)
    return bool(account and account.is_support_agent and account.status == UserAccount.STATUS_ACTIVE)


def can_impersonate(user) -> bool:
    return is_platform_super_admin(user) or is_support_agent(user)


def resolve_workspace_role(user, workspace: Workspace) -> str | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if is_platform_super_admin(user):
        return WorkspaceMembership.ROLE_OWNER
    if workspace.owner_id == user.id:
        return WorkspaceMembership.ROLE_OWNER
    membership = workspace.memberships.filter(user=user, status=WorkspaceMembership.STATUS_ACTIVE).first()
    return membership.role if membership else None


def has_workspace_permission(user, workspace: Workspace, permission: str) -> bool:
    account = _account(user)
    if account and account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED, UserAccount.STATUS_LOCKED}:
        return False
    role = resolve_workspace_role(user, workspace)
    if not role:
        return False
    return permission in WORKSPACE_PERMISSION_MATRIX.get(role, set())


def resolve_site_role(user, site: Site) -> ResolvedSiteRole:
    if not user or not getattr(user, "is_authenticated", False):
        return ResolvedSiteRole(workspace_role=None, site_role=None)
    workspace_role = resolve_workspace_role(user, site.workspace) if site.workspace_id else None
    site_membership = site.memberships.filter(user=user, status=SiteMembership.STATUS_ACTIVE).first()
    site_role = site_membership.role if site_membership else None
    return ResolvedSiteRole(workspace_role=workspace_role, site_role=site_role)


def has_site_permission(user, site: Site, permission: str) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if is_platform_super_admin(user):
        return True
    account = _account(user)
    if account and account.status in {UserAccount.STATUS_DELETED, UserAccount.STATUS_SUSPENDED, UserAccount.STATUS_LOCKED}:
        return False
    resolved = resolve_site_role(user, site)
    workspace_permissions = WORKSPACE_TO_SITE_PERMISSIONS.get(resolved.workspace_role or "", set())
    site_permissions = SITE_PERMISSION_MATRIX.get(resolved.site_role or "", set())
    return permission in workspace_permissions or permission in site_permissions
