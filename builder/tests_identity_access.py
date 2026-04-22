from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from core.models import Site, SiteMembership, Workspace, WorkspaceMembership


User = get_user_model()


class IdentityAccessEndpointsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.platform_admin = User.objects.create_superuser(
            username="platform-admin",
            email="platform-admin@example.com",
            password="VerySecurePass123",
        )
        self.owner = User.objects.create_user(
            username="workspace-owner",
            email="workspace-owner@example.com",
            password="VerySecurePass123",
        )
        self.member = User.objects.create_user(
            username="workspace-member",
            email="workspace-member@example.com",
            password="VerySecurePass123",
        )
        self.workspace = Workspace.objects.create(name="Acme Workspace", slug="acme-workspace", owner=self.owner)
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceMembership.ROLE_OWNER,
            status=WorkspaceMembership.STATUS_ACTIVE,
            invited_by=self.owner,
            accepted_at=timezone.now(),
        )
        self.site = Site.objects.create(name="Acme Site", slug="acme-site", workspace=self.workspace)

    def test_site_members_route_supports_get_and_post(self):
        self.client.force_login(self.owner)
        create_response = self.client.post(
            f"/api/sites/{self.site.id}/members/",
            {
                "user_id": self.member.id,
                "role": SiteMembership.ROLE_EDITOR,
                "status": SiteMembership.STATUS_ACTIVE,
            },
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self.client.get(f"/api/sites/{self.site.id}/members/")
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertTrue(any(item["user"]["id"] == self.member.id for item in payload))

    def test_platform_admin_can_manage_site_memberships(self):
        self.client.force_login(self.platform_admin)
        create_response = self.client.post(
            f"/api/platform-admin/sites/{self.site.id}/memberships/",
            {
                "user_id": self.member.id,
                "role": SiteMembership.ROLE_VIEWER,
                "status": SiteMembership.STATUS_ACTIVE,
            },
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 201)
        membership_id = create_response.json()["id"]

        patch_response = self.client.patch(
            f"/api/platform-admin/sites/{self.site.id}/memberships/{membership_id}/",
            {
                "role": SiteMembership.ROLE_EDITOR,
            },
            content_type="application/json",
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["role"], SiteMembership.ROLE_EDITOR)

        delete_response = self.client.delete(f"/api/platform-admin/sites/{self.site.id}/memberships/{membership_id}/")
        self.assertEqual(delete_response.status_code, 204)

    def test_email_verification_resend_alias_endpoint(self):
        response = self.client.post(
            "/api/auth/email-verification/resend/",
            {"email": self.owner.email},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202)
