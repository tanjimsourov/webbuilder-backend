from __future__ import annotations

from django.test import Client, TestCase
from django.utils import timezone

from cms.models import Page
from core.test_utils import create_user_workspace_site
from forms.models import Form, FormSubmission


class PublicRuntimeFormsTests(TestCase):
    def setUp(self):
        _, _, self.site = create_user_workspace_site(
            username="forms-owner",
            email="forms-owner@example.com",
            workspace_name="Forms Workspace",
            workspace_slug="forms-workspace",
            site_name="Forms Site",
            site_slug="forms-site",
        )
        self.client = Client()
        self.page = Page.objects.create(
            site=self.site,
            title="Contact",
            slug="contact",
            path="/contact/",
            status=Page.STATUS_PUBLISHED,
            published_at=timezone.now(),
        )
        self.form = Form.objects.create(
            site=self.site,
            name="Contact Form",
            slug="contact-form",
            status=Form.STATUS_ACTIVE,
            fields=[
                {
                    "id": "email",
                    "type": "email",
                    "label": "Email",
                    "name": "email",
                    "required": True,
                },
            ],
            honeypot_field="website",
        )

    def test_runtime_schema_returns_404_when_forms_feature_disabled(self):
        self.site.settings = {"features": {"forms": {"enabled": False}}}
        self.site.save(update_fields=["settings", "updated_at"])

        response = self.client.get(f"/api/public/runtime/forms/{self.form.slug}/?site={self.site.id}")

        self.assertEqual(response.status_code, 404)
        self.assertIn("disabled", response.json()["detail"].lower())

    def test_runtime_submission_creates_form_submission(self):
        response = self.client.post(
            f"/api/public/runtime/forms/{self.form.slug}/submit/?site={self.site.id}",
            {
                "payload": {"email": "lead@example.com"},
                "page_path": "/contact/",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        submission = FormSubmission.objects.get(pk=payload["submission_id"])
        self.assertEqual(submission.site_id, self.site.id)
        self.assertEqual(submission.form_name, self.form.slug)
        self.assertEqual(submission.page_id, self.page.id)

    def test_runtime_submission_rejects_missing_required_fields(self):
        response = self.client.post(
            f"/api/public/runtime/forms/{self.form.slug}/submit/?site={self.site.id}",
            {
                "payload": {},
                "page_path": "/contact/",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())
        self.assertFalse(FormSubmission.objects.exists())

    def test_runtime_submission_honeypot_returns_success_without_persisting(self):
        response = self.client.post(
            f"/api/public/runtime/forms/{self.form.slug}/submit/?site={self.site.id}",
            {
                "payload": {"email": "bot@example.com", "website": "https://spam.example"},
                "page_path": "/contact/",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(FormSubmission.objects.exists())
