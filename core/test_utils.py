from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from core.models import Site, Workspace, WorkspaceMembership


User = get_user_model()


def create_user_workspace_site(
    *,
    username: str,
    email: str,
    password: str = "VerySecurePass123",
    workspace_name: str = "Test Workspace",
    workspace_slug: str = "test-workspace",
    site_name: str = "Test Site",
    site_slug: str = "test-site",
):
    """
    Create a user, owned workspace membership, and site for tests.

    Returns `(user, workspace, site)`.
    """
    user = User.objects.create_user(username=username, email=email, password=password)
    workspace = Workspace.objects.create(name=workspace_name, slug=workspace_slug, owner=user)
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMembership.ROLE_OWNER,
        invited_by=user,
        accepted_at=timezone.now(),
    )
    site = Site.objects.create(name=site_name, slug=site_slug, workspace=workspace)
    return user, workspace, site


def authenticated_client(user) -> Client:
    """Return a Django test client authenticated as `user`."""
    client = Client()
    client.force_login(user)
    return client
