from __future__ import annotations

import hashlib

from core.models import FeatureFlag, FeatureFlagAssignment


def _bucket_for(seed: str, key: str) -> int:
    digest = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def is_feature_enabled(
    key: str,
    *,
    user=None,
    workspace=None,
    site=None,
    default: bool = False,
) -> bool:
    flag = FeatureFlag.objects.filter(key=key, is_active=True).first()
    if not flag:
        return default

    queryset = FeatureFlagAssignment.objects.filter(flag=flag)
    if user is not None:
        user_assignment = queryset.filter(user=user).first()
        if user_assignment is not None:
            return bool(user_assignment.enabled)
    if workspace is not None:
        workspace_assignment = queryset.filter(workspace=workspace).first()
        if workspace_assignment is not None:
            return bool(workspace_assignment.enabled)
    if site is not None:
        site_assignment = queryset.filter(site=site).first()
        if site_assignment is not None:
            return bool(site_assignment.enabled)

    if not flag.enabled_by_default:
        return False
    rollout = int(max(0, min(int(flag.rollout_percentage or 0), 100)))
    if rollout >= 100:
        return True
    if rollout <= 0:
        return False

    seed = "global"
    if user is not None and getattr(user, "pk", None):
        seed = f"user:{user.pk}"
    elif workspace is not None and getattr(workspace, "pk", None):
        seed = f"workspace:{workspace.pk}"
    elif site is not None and getattr(site, "pk", None):
        seed = f"site:{site.pk}"
    return _bucket_for(seed, key) < rollout
