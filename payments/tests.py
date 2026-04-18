from __future__ import annotations

import json
from unittest import mock, skipIf

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings

from payments.models import Subscription, SubscriptionPlan
from payments import views as payment_views
from payments import services as payment_services


User = get_user_model()


class PaymentsSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="billing-user",
            email="billing@example.com",
            password="VerySecurePass123",
        )
        self.plan = SubscriptionPlan.objects.create(
            name="Starter",
            slug="starter",
            amount=1500,
            price="15.00",
            currency="usd",
            interval="month",
            is_active=True,
        )
        self.subscription = Subscription.objects.create(
            customer=self.user,
            plan=self.plan,
            status="active",
        )
        self.request_factory = RequestFactory()

    def test_subscription_update_endpoint_is_not_writable(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/payments/subscriptions/{self.subscription.id}/",
            data=json.dumps({"status": "canceled"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, "active")

    def test_stripe_webhook_returns_503_when_not_configured(self):
        response = self.client.post(
            "/api/payments/webhooks/stripe/",
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=sig",
        )
        self.assertEqual(response.status_code, 503)

    @override_settings(STRIPE_SECRET_KEY="sk_test_configured")
    def test_checkout_session_for_one_time_plan_omits_recurring_price_data(self):
        request = self.request_factory.post("/api/payments/checkout/session/")
        request.user = self.user
        request.META["HTTP_HOST"] = "testserver"

        stripe_mock = mock.MagicMock()
        stripe_mock.checkout.Session.create.return_value = {"id": "cs_test", "url": "https://checkout.stripe.test"}
        with mock.patch("payments.services.stripe", stripe_mock):
            payload = payment_services.create_checkout_session(request, self.plan, customer_email=self.user.email)

        self.assertEqual(payload["id"], "cs_test")
        kwargs = stripe_mock.checkout.Session.create.call_args.kwargs
        self.assertEqual(kwargs["mode"], "payment")
        line_item = kwargs["line_items"][0]["price_data"]
        self.assertNotIn("recurring", line_item)

    @skipIf(payment_views.stripe is None, "Stripe SDK is not installed")
    @override_settings(STRIPE_WEBHOOK_SECRET="whsec_test", PAYMENT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS=60)
    def test_stripe_webhook_deduplicates_event_ids(self):
        event = {
            "id": "evt_duplicate_1",
            "type": "invoice.paid",
            "data": {"object": {"id": "in_123"}},
        }
        with mock.patch("payments.views.stripe.Webhook.construct_event", return_value=event), mock.patch(
            "payments.views.handle_webhook"
        ) as handle_webhook:
            first = self.client.post(
                "/api/payments/webhooks/stripe/",
                data=b'{"id":"evt_duplicate_1"}',
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )
            second = self.client.post(
                "/api/payments/webhooks/stripe/",
                data=b'{"id":"evt_duplicate_1"}',
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(handle_webhook.call_count, 1)
        self.assertTrue(second.json().get("duplicate"))

    @skipIf(payment_views.stripe is None, "Stripe SDK is not installed")
    @override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
    def test_stripe_webhook_rejects_invalid_signature(self):
        signature_error = payment_views.stripe.error.SignatureVerificationError("invalid signature", "sig")
        with mock.patch("payments.views.stripe.Webhook.construct_event", side_effect=signature_error):
            response = self.client.post(
                "/api/payments/webhooks/stripe/",
                data=b'{"id":"evt_1"}',
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid signature.")
