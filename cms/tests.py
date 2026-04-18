from __future__ import annotations

from django.test import Client, TestCase
from django.utils import timezone

from cms.models import Page
from core.test_utils import create_user_workspace_site


class PublicRuntimeCmsTests(TestCase):
    def setUp(self):
        _, _, self.site = create_user_workspace_site(
            username="cms-owner",
            email="cms-owner@example.com",
            workspace_name="CMS Workspace",
            workspace_slug="cms-workspace",
            site_name="CMS Site",
            site_slug="cms-site",
        )
        self.client = Client()
        self.page = Page.objects.create(
            site=self.site,
            title="About",
            slug="about",
            path="/about/",
            status=Page.STATUS_PUBLISHED,
            published_at=timezone.now(),
            seo={"meta_title": "About - CMS Site"},
        )

    def test_runtime_page_lookup_requires_path(self):
        response = self.client.get(f"/api/public/runtime/page/?site={self.site.id}")

        self.assertEqual(response.status_code, 400)
        self.assertIn("path", response.json())

    def test_runtime_page_lookup_returns_published_page_payload(self):
        response = self.client.get(
            f"/api/public/runtime/page/?site={self.site.id}&path=/about/",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["site"]["id"], self.site.id)
        self.assertEqual(payload["route"]["resolved_path"], "/about/")
        self.assertEqual(payload["page"]["id"], self.page.id)
        self.assertEqual(payload["meta"]["title"], "About - CMS Site")

    def test_runtime_page_lookup_returns_404_for_unpublished_page(self):
        self.page.status = Page.STATUS_DRAFT
        self.page.save(update_fields=["status", "updated_at"])

        response = self.client.get(
            f"/api/public/runtime/page/?site={self.site.id}&path=/about/",
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"].lower())
