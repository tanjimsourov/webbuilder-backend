"""Authorization policy helpers."""

from .access import (
    PlatformPermission,
    SitePermission,
    WorkspacePermission,
    can_impersonate,
    has_site_permission,
    has_workspace_permission,
    is_platform_super_admin,
    is_support_agent,
    resolve_site_role,
    resolve_workspace_role,
)

__all__ = [
    "PlatformPermission",
    "SitePermission",
    "WorkspacePermission",
    "can_impersonate",
    "has_site_permission",
    "has_workspace_permission",
    "is_platform_super_admin",
    "is_support_agent",
    "resolve_site_role",
    "resolve_workspace_role",
]
