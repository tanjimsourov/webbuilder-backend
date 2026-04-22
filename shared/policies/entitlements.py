from __future__ import annotations

from typing import Any

from django.utils import timezone

from payments.models import PlanEntitlement, WorkspaceSubscription


def active_workspace_subscription(workspace) -> WorkspaceSubscription | None:
    subscription = WorkspaceSubscription.objects.filter(workspace=workspace).select_related("plan").first()
    if not subscription:
        return None
    if subscription.status == WorkspaceSubscription.STATUS_CANCELLED:
        return None
    if subscription.current_period_end and subscription.current_period_end < timezone.now():
        return None
    return subscription


def entitlement_for_workspace(workspace, code: str) -> PlanEntitlement | None:
    subscription = active_workspace_subscription(workspace)
    if not subscription:
        return None
    return PlanEntitlement.objects.filter(plan=subscription.plan, code=code, enabled=True).first()


def entitlement_limit(workspace, code: str, *, default: int | None = None) -> int | None:
    entitlement = entitlement_for_workspace(workspace, code)
    if entitlement is None:
        return default
    if entitlement.is_unlimited:
        return None
    return int(entitlement.limit_value)


def is_feature_enabled(workspace, code: str, *, default: bool = False) -> bool:
    entitlement = entitlement_for_workspace(workspace, code)
    if entitlement is None:
        return default
    return bool(entitlement.enabled and (entitlement.is_unlimited or entitlement.limit_value > 0))


def usage_limit_state(workspace, code: str, used_value: int, *, default_limit: int | None = None) -> dict[str, Any]:
    limit = entitlement_limit(workspace, code, default=default_limit)
    unlimited = limit is None
    used = int(max(0, used_value))
    remaining = None if unlimited else max(0, int(limit) - used)
    exceeded = False if unlimited else used > int(limit)
    return {
        "code": code,
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "unlimited": unlimited,
        "exceeded": exceeded,
    }
