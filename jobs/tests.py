from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from builder.models import Job, Page, PlatformEmailCampaign, Workspace, WorkspaceMembership
from core.models import Site
from jobs.tasks import retry_webhook_delivery, send_notification_email
from builder import jobs as builder_jobs
from notifications.models import Webhook, WebhookDelivery


User = get_user_model()


class JobsTaskRegressionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="jobs-owner",
            email="jobs-owner@example.com",
            password="VerySecurePass123",
        )
        self.workspace = Workspace.objects.create(name="Jobs Workspace", slug="jobs-workspace", owner=self.owner)
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=self.owner,
        )
        self.site = Site.objects.create(name="Jobs Site", slug="jobs-site", workspace=self.workspace)

    def test_retry_webhook_delivery_queues_due_deliveries(self):
        webhook = Webhook.objects.create(
            site=self.site,
            name="jobs-webhook",
            url="https://hooks.example.com/jobs",
            event=Webhook.EVENT_PAGE_PUBLISHED,
            status=Webhook.STATUS_ACTIVE,
        )
        delivery = WebhookDelivery.objects.create(
            webhook=webhook,
            event=Webhook.EVENT_PAGE_PUBLISHED,
            payload={"page_id": 1},
            status=WebhookDelivery.STATUS_FAILED,
            attempt_count=1,
            max_attempts=5,
            next_attempt_at=timezone.now() - timedelta(minutes=1),
        )

        result = retry_webhook_delivery()
        self.assertEqual(result["queued"], 1)
        self.assertTrue(
            Job.objects.filter(job_type="deliver_webhook", payload__delivery_id=delivery.id).exists()
        )

    def test_send_notification_email_processes_campaign_by_id(self):
        campaign = PlatformEmailCampaign.objects.create(
            name="Ops Campaign",
            subject="Platform update",
            body_text="This is a release notification.",
            audience_type=PlatformEmailCampaign.AUDIENCE_WORKSPACE_OWNERS,
            status=PlatformEmailCampaign.STATUS_DRAFT,
            created_by=self.owner,
        )

        result = send_notification_email(campaign.id)
        campaign.refresh_from_db()

        self.assertEqual(result["processed"], 1)
        self.assertIn(campaign.status, {PlatformEmailCampaign.STATUS_SENT, PlatformEmailCampaign.STATUS_FAILED})

    def test_queue_search_index_is_idempotent_for_same_object(self):
        page = Page.objects.create(site=self.site, title="Search Page", slug="search-page", path="/search-page/")

        first = builder_jobs.queue_search_index("page", page.id)
        second = builder_jobs.queue_search_index("page", page.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(Job.objects.filter(job_type="search_index").count(), 1)

    def test_handle_search_index_job_indexes_page(self):
        page = Page.objects.create(site=self.site, title="Indexed Page", slug="indexed-page", path="/indexed-page/")
        job = Job.objects.create(job_type="search_index", job_id="search-job-1", payload={"object_type": "page", "object_id": page.id})

        with mock.patch("builder.search_services.search_service.index_page", return_value=True) as index_page:
            result = builder_jobs.handle_search_index(job)

        self.assertTrue(result["indexed"])
        index_page.assert_called_once()

    def test_handle_deliver_webhook_skips_when_delivery_lock_exists(self):
        webhook = Webhook.objects.create(
            site=self.site,
            name="lock-webhook",
            url="https://hooks.example.com/locked",
            event=Webhook.EVENT_PAGE_PUBLISHED,
            status=Webhook.STATUS_ACTIVE,
        )
        delivery = WebhookDelivery.objects.create(
            webhook=webhook,
            event=Webhook.EVENT_PAGE_PUBLISHED,
            payload={"page_id": 5},
            status=WebhookDelivery.STATUS_PENDING,
            next_attempt_at=timezone.now(),
        )
        job = Job.objects.create(
            job_type="deliver_webhook",
            job_id="deliver-lock-job",
            payload={"delivery_id": delivery.id},
        )

        with mock.patch("builder.jobs.cache.add", return_value=False):
            result = builder_jobs.handle_deliver_webhook(job)

        self.assertTrue(result["skipped"])
        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 0)

    def test_process_pending_jobs_claims_only_requested_batch_size(self):
        executed: list[int] = []

        @builder_jobs.register_job("test_claim_batch")
        def _test_handler(job):
            executed.append(job.id)
            return {"ok": True}

        try:
            Job.objects.create(job_type="test_claim_batch", job_id="claim-job-1", payload={})
            Job.objects.create(job_type="test_claim_batch", job_id="claim-job-2", payload={})

            processed = builder_jobs.process_pending_jobs(batch_size=1)

            self.assertEqual(processed, 1)
            self.assertEqual(len(executed), 1)
            self.assertEqual(Job.objects.filter(job_type="test_claim_batch", status=Job.STATUS_COMPLETED).count(), 1)
            self.assertEqual(Job.objects.filter(job_type="test_claim_batch", status=Job.STATUS_PENDING).count(), 1)
        finally:
            builder_jobs._job_handlers.pop("test_claim_batch", None)
