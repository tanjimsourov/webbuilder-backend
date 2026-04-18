from __future__ import annotations

from django.test import TestCase

from builder.models import Page, PageRevision
from builder.services import create_revision
from core.test_utils import create_user_workspace_site


class PageRevisionSafetyTests(TestCase):
    def test_create_revision_skips_when_legacy_fk_target_row_is_missing(self):
        _, _, site = create_user_workspace_site(
            username="revision-owner",
            email="revision-owner@example.com",
            workspace_name="Revision Workspace",
            workspace_slug="revision-workspace",
            site_name="Revision Site",
            site_slug="revision-site",
        )
        page = Page.objects.create(site=site, title="Home", slug="home", path="/")

        revision = create_revision(page, "Draft snapshot")

        self.assertIsNone(revision)
        self.assertEqual(PageRevision.objects.count(), 0)
