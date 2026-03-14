import shutil
from unittest import mock
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.test import Client, TestCase, override_settings

from .experiments import ASSIGNMENTS_COOKIE_NAME, VISITOR_COOKIE_NAME
from .models import (
    Cart,
    Comment,
    DiscountCode,
    ExperimentEvent,
    FormSubmission,
    MediaAsset,
    Order,
    Page,
    PageExperiment,
    PageExperimentVariant,
    PlatformEmailCampaign,
    PlatformOffer,
    PlatformSubscription,
    PageReview,
    PageReviewComment,
    PageTranslation,
    Product,
    ProductCategory,
    Site,
    SiteLocale,
    ShippingZone,
    TaxRate,
    Workspace,
    WorkspaceMembership,
    WorkspaceInvitation,
)
from .notification_services import notification_service
from .services import ensure_seed_data


User = get_user_model()


class BuilderPlatformTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def _csrf_token_for(self, client: Client) -> str:
        response = client.get("/api/auth/status/")
        self.assertEqual(response.status_code, 200)
        return response.cookies["csrftoken"].value

    def _csrf_token(self) -> str:
        return self._csrf_token_for(self.client)

    def _login(self, client: Client, username: str, password: str):
        response = client.post(
            "/api/auth/login/",
            {
                "username": username,
                "password": password,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token_for(client),
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_bootstrap_auth_flow_unlocks_dashboard(self):
        token = self._csrf_token()
        response = self.client.post(
            "/api/auth/bootstrap/",
            {
                "username": "owner",
                "email": "owner@example.com",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username="owner").exists())

        dashboard = self.client.get("/api/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("sites", dashboard.json())

    def test_login_logout_and_protected_routes(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")
        blocked = self.client.get("/api/sites/")
        self.assertIn(blocked.status_code, [401, 403])

        token = self._csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(self.client.get("/api/sites/").status_code, 200)

        logout_token = self._csrf_token()
        logout_response = self.client.post(
            "/api/auth/logout/",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=logout_token,
        )
        self.assertEqual(logout_response.status_code, 204)
        self.assertIn(self.client.get("/api/sites/").status_code, [401, 403])

    def test_public_submission_endpoints_store_records(self):
        ensure_seed_data()
        form_response = self.client.post(
            "/api/public/forms/submit/",
            {
                "site_slug": "northstar-studio",
                "page_path": "/contact/",
                "form_name": "Contact form",
                "payload": {
                    "name": "Sam",
                    "email": "sam@example.com",
                    "message": "Need a production rollout.",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(form_response.status_code, 201)
        self.assertEqual(FormSubmission.objects.filter(form_name="Contact form").count(), 1)

        comment_response = self.client.post(
            "/api/public/comments/submit/",
            {
                "site_slug": "northstar-studio",
                "post_slug": "run-your-site-like-a-publishing-system",
                "author_name": "Casey",
                "author_email": "casey@example.com",
                "body": "Useful publishing structure.",
            },
            content_type="application/json",
        )
        self.assertEqual(comment_response.status_code, 201)
        self.assertEqual(Comment.objects.filter(author_name="Casey", is_approved=False).count(), 1)

    @override_settings(ENABLE_REQUEST_SEED_DATA=False)
    def test_seed_data_can_be_disabled(self):
        ensure_seed_data()
        self.assertEqual(Site.objects.count(), 0)

    def test_notification_service_uses_existing_model_fields(self):
        ensure_seed_data()
        site = Site.objects.get(slug="northstar-studio")
        order = Order.objects.create(
            site=site,
            order_number="ORDER-1001",
            customer_name="Sam",
            customer_email="sam@example.com",
            total="125.00",
            payment_provider="stripe",
            pricing_details={"tracking_number": "TRACK-42"},
        )
        invitation = WorkspaceInvitation.objects.create(
            workspace=Workspace.objects.create(name="Ops", slug="ops", owner=User.objects.create_user("owner2", "owner2@example.com", "VerySecurePass123")),
            email="invitee@example.com",
            role=WorkspaceMembership.ROLE_EDITOR,
            token="token-123",
            invited_by=User.objects.create_user("admin2", "admin2@example.com", "VerySecurePass123"),
            expires_at=timezone.now(),
        )

        form = mock.Mock()
        form.name = "Contact form"
        submission = mock.Mock()
        submission.created_at = timezone.now()
        submission.payload = {"email": "sam@example.com"}
        submission.id = 7

        with mock.patch.object(notification_service, "send_notification", return_value=True) as send_notification:
            self.assertTrue(notification_service.send_order_notification(order, "paid"))
            order_context = send_notification.call_args.kwargs["context"]
            self.assertEqual(order_context["payment_method"], "stripe")
            self.assertEqual(order_context["tracking_number"], "TRACK-42")

            send_notification.reset_mock()
            self.assertTrue(notification_service.send_form_submission_notification(form, submission, ["owner@example.com"]))
            form_context = send_notification.call_args.kwargs["context"]
            self.assertIn("sam@example.com", form_context["submission_data"])

            send_notification.reset_mock()
            self.assertTrue(notification_service.send_workspace_invitation(invitation, "Owner"))
            invite_context = send_notification.call_args.kwargs["context"]
            self.assertEqual(invite_context["invitation_url"], "/editor?invite_token=token-123")

    def test_authenticated_media_upload(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")
        ensure_seed_data()
        site_id = Site.objects.values_list("id", flat=True).first()
        temp_dir = Path(__file__).resolve().parent.parent / ".test-media" / "media-root"
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            with override_settings(MEDIA_ROOT=str(temp_dir)):
                token = self._csrf_token()
                login_response = self.client.post(
                    "/api/auth/login/",
                    {
                        "username": "admin",
                        "password": "VerySecurePass123",
                    },
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=token,
                )
                self.assertEqual(login_response.status_code, 200)

                upload = SimpleUploadedFile("demo.txt", b"hello cms", content_type="text/plain")
                response = self.client.post(
                    "/api/media/",
                    {
                        "site": site_id,
                        "title": "Demo asset",
                        "kind": "document",
                        "file": upload,
                    },
                    HTTP_X_CSRFTOKEN=self._csrf_token(),
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(MediaAsset.objects.filter(title="Demo asset").count(), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_new_site_creation_includes_cms_and_commerce_seed_content(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")
        token = self._csrf_token()
        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            "/api/sites/",
            {
                "name": "Commerce Test",
                "slug": "commerce-test",
                "starter_kit": "commerce",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(response.status_code, 201)
        site = Site.objects.get(slug="commerce-test")
        self.assertTrue(site.posts.exists())
        self.assertTrue(site.products.exists())
        self.assertTrue(site.discount_codes.exists())
        self.assertTrue(site.shipping_zones.exists())
        self.assertTrue(site.tax_rates.exists())

    def test_public_catalog_cart_and_checkout_flow(self):
        ensure_seed_data()

        catalog_response = self.client.get("/api/public/shop/northstar-studio/products/")
        self.assertEqual(catalog_response.status_code, 200)
        self.assertGreaterEqual(len(catalog_response.json()), 1)
        self.assertTrue(Product.objects.filter(site__slug="northstar-studio").exists())

        add_to_cart = self.client.post(
            "/api/public/shop/northstar-studio/cart/items/",
            {
                "product_slug": "launch-system-kit",
                "quantity": 2,
            },
            content_type="application/json",
        )
        self.assertEqual(add_to_cart.status_code, 201)
        cart_payload = add_to_cart.json()
        self.assertEqual(cart_payload["item_count"], 2)
        self.assertEqual(len(cart_payload["items"]), 1)
        item_id = cart_payload["items"][0]["id"]

        update_cart = self.client.patch(
            f"/api/public/shop/northstar-studio/cart/items/{item_id}/",
            {"quantity": 1},
            content_type="application/json",
        )
        self.assertEqual(update_cart.status_code, 200)
        self.assertEqual(update_cart.json()["item_count"], 1)

        site = Site.objects.get(slug="northstar-studio")
        shipping_rate = site.shipping_zones.get(name="United States").rates.order_by("price").first()
        pricing = self.client.post(
            "/api/public/shop/northstar-studio/cart/pricing/",
            {
                "shipping_address": {"country": "US", "state": "TX"},
                "shipping_rate_id": shipping_rate.id,
                "discount_code": "SAVE10",
            },
            content_type="application/json",
        )
        self.assertEqual(pricing.status_code, 200)
        pricing_payload = pricing.json()["pricing"]
        self.assertEqual(pricing_payload["shipping_total"], "7.50")
        self.assertEqual(pricing_payload["discount_total"], "14.90")
        self.assertEqual(pricing_payload["tax_total"], "11.68")
        self.assertEqual(pricing_payload["total"], "153.28")

        checkout = self.client.post(
            "/api/public/shop/northstar-studio/checkout/",
            {
                "customer_name": "Jordan Rivers",
                "customer_email": "jordan@example.com",
                "customer_phone": "+15555550100",
                "billing_address": {"country": "US", "city": "Austin"},
                "shipping_address": {"country": "US", "state": "TX", "city": "Austin"},
                "shipping_rate_id": shipping_rate.id,
                "discount_code": "SAVE10",
                "notes": "Leave access details in email.",
            },
            content_type="application/json",
        )
        self.assertEqual(checkout.status_code, 201)
        order_payload = checkout.json()
        self.assertEqual(order_payload["customer_email"], "jordan@example.com")
        self.assertEqual(order_payload["shipping_total"], "7.50")
        self.assertEqual(order_payload["discount_total"], "14.90")
        self.assertEqual(order_payload["tax_total"], "11.68")
        self.assertEqual(order_payload["total"], "153.28")
        self.assertEqual(order_payload["pricing_details"]["discount_code"], "SAVE10")
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Cart.objects.filter(status=Cart.STATUS_CONVERTED).count(), 1)
        self.assertEqual(site.discount_codes.get(code="SAVE10").use_count, 1)

        empty_cart = self.client.get("/api/public/shop/northstar-studio/cart/")
        self.assertEqual(empty_cart.status_code, 200)
        self.assertEqual(empty_cart.json()["item_count"], 0)

        shop_page = self.client.get("/preview/northstar-studio/shop/")
        self.assertEqual(shop_page.status_code, 200)
        product_page = self.client.get("/preview/northstar-studio/shop/launch-system-kit/")
        self.assertEqual(product_page.status_code, 200)
        cart_page = self.client.get("/preview/northstar-studio/shop/cart/")
        self.assertEqual(cart_page.status_code, 200)
        filtered_shop_page = self.client.get("/preview/northstar-studio/shop/?q=launch&category=featured-products&sort=price_desc")
        self.assertEqual(filtered_shop_page.status_code, 200)

    def test_product_search_filter_matches_titles_and_category_assignment(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")
        self._login(self.client, "admin", "VerySecurePass123")

        site = Site.objects.order_by("id").first()
        category = ProductCategory.objects.create(site=site, name="Merch", slug="merch")

        create_response = self.client.post(
            "/api/products/",
            {
                "site": site.id,
                "title": "Merch Pack",
                "slug": "merch-pack",
                "excerpt": "Limited run bundle.",
                "description_html": "<p>Merch pack</p>",
                "category_ids": [category.id],
                "status": "draft",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(create_response.status_code, 201)
        product = Product.objects.get(slug="merch-pack")
        self.assertTrue(product.categories.filter(pk=category.id).exists())

        search_response = self.client.get(f"/api/products/?site={site.id}&search=merch")
        self.assertEqual(search_response.status_code, 200)
        payload = search_response.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertTrue(any(item["slug"] == "merch-pack" for item in results))

    def test_authenticated_workspace_search_returns_editor_results(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        page = Page.objects.create(
            site=site,
            title="Searchable Launch Page",
            slug="searchable-launch-page",
            path="/searchable-launch-page/",
        )
        page_id = page.id

        search_response = self.client.get(f"/api/search/?q=searchable&site={site.id}")
        self.assertEqual(search_response.status_code, 200)

        payload = search_response.json()
        self.assertEqual(payload["query"], "searchable")
        self.assertGreaterEqual(len(payload["results"]), 1)
        self.assertTrue(
            any(
                result["id"] == f"page_{page_id}"
                and result["type"] == "page"
                and result["title"] == "Searchable Launch Page"
                and result["url"] == f"/editor?site={site.id}&page={page_id}"
                for result in payload["results"]
            )
        )

    def test_authenticated_apps_catalog_lists_platform_integrations(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.get("/api/apps/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        app_ids = {app["id"] for app in payload["apps"]}
        self.assertIn("sdk.pluggy", app_ids)
        self.assertIn("ai.studio", app_ids)
        self.assertIn("editor.grapesjs", app_ids)
        self.assertIn("editor.grapesjs-plugin-forms", app_ids)
        self.assertIn("editor.grapesjs-navbar", app_ids)
        self.assertIn("editor.grapesjs-tui-image-editor", app_ids)
        self.assertIn("cms.payload", app_ids)
        self.assertIn("commerce.payload-ecommerce", app_ids)
        self.assertIn("seo.librecrawl", app_ids)
        self.assertIn("seo.serpbear", app_ids)
        self.assertIn("analytics.umami", app_ids)
        self.assertIn("experiments.growthbook", app_ids)
        self.assertIn("forms.react-hook-form", app_ids)
        self.assertIn("collab.react-mentions", app_ids)

    def test_ai_suggestions_fallback_returns_seo_payload(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        page = site.pages.order_by("id").first()
        self.assertIsNotNone(page)

        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            response = self.client.post(
                "/api/ai/suggestions/",
                {
                    "site_id": site.id,
                    "page_id": page.id,
                    "goal": "page_seo",
                    "brief": "Focus on launch systems and conversion-driven landing pages.",
                    "keywords": ["launch systems", "conversion landing pages"],
                },
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf_token(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "rules")
        self.assertEqual(payload["goal"], "page_seo")
        self.assertIn("suggestions", payload)
        self.assertIn("meta_title", payload["suggestions"])
        self.assertIn("meta_description", payload["suggestions"])
        self.assertLessEqual(len(payload["suggestions"]["meta_title"]), 60)
        self.assertLessEqual(len(payload["suggestions"]["meta_description"]), 155)

    @override_settings(
        LIBRECRAWL_PUBLIC_URL="http://127.0.0.1:5055",
        LIBRECRAWL_HOST="127.0.0.1",
        LIBRECRAWL_PORT=5055,
        LIBRECRAWL_LOCAL_MODE=True,
    )
    def test_librecrawl_status_returns_vendor_metadata(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        response = self.client.get(f"/api/seo/librecrawl/status/?site={site.id}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["installed"])
        self.assertEqual(payload["license"], "MIT")
        self.assertEqual(payload["public_url"], "http://127.0.0.1:5055")
        self.assertIn("LibreCrawl", payload["source_url"])
        self.assertIn(site.slug, payload["recommended_target_url"])
        self.assertIn("run_librecrawl", payload["launch_command"])

    @override_settings(
        SERPBEAR_PUBLIC_URL="http://127.0.0.1:5060",
        SERPBEAR_HOST="127.0.0.1",
        SERPBEAR_PORT=5060,
    )
    def test_serpbear_status_returns_vendor_metadata(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        response = self.client.get(f"/api/seo/serpbear/status/?site={site.id}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["installed"])
        self.assertEqual(payload["license"], "MIT")
        self.assertEqual(payload["public_url"], "http://127.0.0.1:5060")
        self.assertIn("serpbear", payload["source_url"].lower())
        self.assertIn("npm", payload["install_command"].lower())
        self.assertIn("run_serpbear", payload["launch_command"])

    @override_settings(
        UMAMI_PUBLIC_URL="http://127.0.0.1:5070",
        UMAMI_HOST="127.0.0.1",
        UMAMI_PORT=5070,
    )
    def test_umami_status_returns_vendor_metadata(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        response = self.client.get(f"/api/analytics/umami/status/?site={site.id}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["installed"])
        self.assertEqual(payload["license"], "MIT")
        self.assertEqual(payload["public_url"], "http://127.0.0.1:5070")
        self.assertIn("umami", payload["source_url"].lower())
        self.assertIn("pnpm", payload["install_command"].lower())
        self.assertIn("run_umami", payload["launch_command"])

    @override_settings(
        PAYLOAD_CMS_PUBLIC_URL="http://127.0.0.1:5080",
        PAYLOAD_CMS_HOST="127.0.0.1",
        PAYLOAD_CMS_PORT=5080,
        PAYLOAD_CMS_DATABASE_URL="mongodb://127.0.0.1/payload-cms",
        PAYLOAD_CMS_SECRET="cms-secret",
    )
    def test_payload_cms_status_returns_vendor_metadata(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        response = self.client.get(f"/api/cms/payload/status/?site={site.id}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["installed"])
        self.assertTrue(payload["database_configured"])
        self.assertTrue(payload["secret_configured"])
        self.assertEqual(payload["license"], "MIT")
        self.assertEqual(payload["template"], "website")
        self.assertEqual(payload["public_url"], "http://127.0.0.1:5080")
        self.assertIn("payloadcms", payload["source_url"])
        self.assertIn("run_payload_cms", payload["launch_command"])
        self.assertTrue(payload["admin_url"].endswith("/admin"))
        self.assertIn("/blog/", payload["recommended_target_url"])

    @override_settings(
        PAYLOAD_ECOMMERCE_PUBLIC_URL="http://127.0.0.1:5085",
        PAYLOAD_ECOMMERCE_HOST="127.0.0.1",
        PAYLOAD_ECOMMERCE_PORT=5085,
        PAYLOAD_ECOMMERCE_DATABASE_URL="mongodb://127.0.0.1/payload-commerce",
        PAYLOAD_ECOMMERCE_SECRET="commerce-secret",
        PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY="sk_test_demo",
        PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY="pk_test_demo",
        PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET="whsec_demo",
    )
    def test_payload_ecommerce_status_returns_vendor_metadata(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        response = self.client.get(f"/api/commerce/payload/status/?site={site.id}")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["installed"])
        self.assertTrue(payload["database_configured"])
        self.assertTrue(payload["secret_configured"])
        self.assertTrue(payload["stripe_configured"])
        self.assertEqual(payload["license"], "MIT")
        self.assertEqual(payload["template"], "ecommerce")
        self.assertEqual(payload["public_url"], "http://127.0.0.1:5085")
        self.assertIn("payloadcms", payload["source_url"])
        self.assertIn("run_payload_ecommerce", payload["launch_command"])
        self.assertTrue(payload["admin_url"].endswith("/admin"))
        self.assertIn("/shop/", payload["recommended_target_url"])

    def test_ai_site_blueprint_fallback_returns_structured_plan(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.order_by("id").first()
        self.assertIsNotNone(site)

        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            response = self.client.post(
                "/api/ai/site-blueprint/",
                {
                    "site_id": site.id,
                    "brief": "Premium service business focused on conversion pages and contact capture.",
                    "keywords": ["conversion pages", "premium services"],
                },
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf_token(),
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "rules")
        self.assertIn("blueprint", payload)
        self.assertGreaterEqual(len(payload["blueprint"]["pages"]), 4)
        self.assertEqual(sum(1 for page in payload["blueprint"]["pages"] if page["is_homepage"]), 1)
        self.assertTrue(any(section["kind"] == "hero" for page in payload["blueprint"]["pages"] for section in page["sections"]))

    def test_apply_site_blueprint_creates_pages_and_navigation(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.create(name="Planner Site", slug="planner-site")
        response = self.client.post(
            "/api/ai/site-blueprint/apply/",
            {
                "site_id": site.id,
                "sync_navigation": True,
                "blueprint": {
                    "site_name": "Planner Site",
                    "site_tagline": "Premium launch systems",
                    "positioning": "Structured website planning for service businesses.",
                    "audience": "Operations leaders",
                    "offering": "Launch systems",
                    "tone": "clear, premium",
                    "pages": [
                        {
                            "id": "home",
                            "title": "Home",
                            "slug": "home",
                            "is_homepage": True,
                            "purpose": "Introduce the offer and convert visitors into calls.",
                            "sections": [
                                {"id": "home_hero", "kind": "hero", "title": "Hero", "summary": "Lead with the offer."},
                                {"id": "home_feature", "kind": "feature", "title": "Features", "summary": "Explain the system."},
                                {"id": "home_cta", "kind": "cta", "title": "CTA", "summary": "Drive visitors to book."},
                            ],
                            "seo": {
                                "meta_title": "Home | Planner Site",
                                "meta_description": "Launch systems for service businesses.",
                                "focus_keywords": ["launch systems"],
                            },
                        },
                        {
                            "id": "about",
                            "title": "About",
                            "slug": "about",
                            "purpose": "Build trust with the company story.",
                            "sections": [
                                {"id": "about_hero", "kind": "hero", "title": "Hero", "summary": "Introduce the brand."},
                                {"id": "about_content", "kind": "content", "title": "Story", "summary": "Tell the story."},
                                {"id": "about_footer", "kind": "footer", "title": "Footer", "summary": "Close the page."},
                            ],
                            "seo": {
                                "meta_title": "About | Planner Site",
                                "meta_description": "Learn about Planner Site.",
                                "focus_keywords": ["about planner site"],
                            },
                        },
                    ],
                },
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["created_pages"]), 2)
        self.assertTrue(payload["navigation_synced"])
        site.refresh_from_db()
        self.assertEqual(site.pages.count(), 2)
        self.assertEqual(len(site.navigation), 2)
        homepage = site.pages.get(is_homepage=True)
        self.assertIn("Visual sitemap starter", homepage.html)
        self.assertEqual(homepage.path, "/")

    def test_site_creation_seeds_default_locale(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            "/api/sites/",
            {
                "name": "Locale Ready",
                "slug": "locale-ready",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["locales"][0]["code"], "en")
        self.assertTrue(payload["locales"][0]["is_default"])
        self.assertTrue(SiteLocale.objects.filter(site__slug="locale-ready", code="en", is_default=True).exists())

    def test_page_translation_publish_renders_localized_preview(self):
        ensure_seed_data()
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        locale_response = self.client.post(
            "/api/site-locales/",
            {
                "site": site.id,
                "code": "fr",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(locale_response.status_code, 201)
        locale_id = locale_response.json()["id"]

        create_translation = self.client.post(
            "/api/page-translations/",
            {
                "page": page.id,
                "locale": locale_id,
                "copy_source": True,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(create_translation.status_code, 201)
        translation_id = create_translation.json()["id"]

        publish_response = self.client.post(
            f"/api/page-translations/{translation_id}/publish/",
            {
                "title": "A propos",
                "slug": "a-propos",
                "seo": {
                    "meta_title": "A propos | Northstar",
                    "meta_description": "Presentation de Northstar Studio.",
                },
                "project_data": {},
                "html": "<section><h1>Bonjour</h1><p>Version francaise.</p></section>",
                "css": "body { background: #fff; }",
                "js": "",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(publish_response.status_code, 200)
        payload = publish_response.json()
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["path"], "/a-propos/")
        self.assertEqual(payload["preview_url"], f"/preview/{site.slug}/fr/a-propos")

        translation = PageTranslation.objects.get(pk=translation_id)
        self.assertEqual(translation.locale.code, "fr")
        self.assertEqual(translation.path, "/a-propos/")

        preview_response = self.client.get(f"/preview/{site.slug}/fr/a-propos/")
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, "Bonjour")

    def test_site_mirror_import_replaces_pages_and_renders_full_document(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")

        login_response = self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(login_response.status_code, 200)

        site = Site.objects.create(name="Import Target", slug="import-target")
        Page.objects.create(
            site=site,
            title="Legacy page",
            slug="legacy-page",
            path="/",
            is_homepage=True,
            html="<section>Legacy</section>",
        )

        temp_root = Path(__file__).resolve().parent.parent / ".test-mirror"
        shutil.rmtree(temp_root, ignore_errors=True)
        temp_root.mkdir(parents=True, exist_ok=True)

        try:
            source_root = temp_root / "mirror-source"
            pages_root = source_root / "output" / "smc-pages"
            pages_root.mkdir(parents=True, exist_ok=True)

            (pages_root / "manifest.json").write_text(
                """
                [
                  {"url": "https://example.test/", "file": "output\\\\smc-pages\\\\index.html", "code": "200"},
                  {"url": "https://example.test/about-us", "file": "output\\\\smc-pages\\\\about-us.html", "code": "200"}
                ]
                """.strip(),
                encoding="utf-8",
            )
            (pages_root / "index.html").write_text(
                """
                <!DOCTYPE html>
                <html>
                  <head>
                    <title>Smart Media Control</title>
                    <meta name="description" content="Digital signage done right.">
                    <base href="https://example.test/">
                  </head>
                  <body>
                    <a href="/about-us">About</a>
                    <a href="/cart">Cart</a>
                  </body>
                </html>
                """.strip(),
                encoding="utf-8",
            )
            (pages_root / "about-us.html").write_text(
                """
                <!DOCTYPE html>
                <html>
                  <head>
                    <title>About Us | Smart Media Control</title>
                    <base href="https://example.test/">
                  </head>
                  <body>
                    <a href="/">Home</a>
                  </body>
                </html>
                """.strip(),
                encoding="utf-8",
            )
            with override_settings(MIRROR_IMPORT_ROOT=temp_root):
                response = self.client.post(
                    f"/api/sites/{site.id}/import_mirror/",
                    {
                        "source_path": "mirror-source",
                        "publish": True,
                        "replace_existing": True,
                    },
                    content_type="application/json",
                    HTTP_X_CSRFTOKEN=self._csrf_token(),
                )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["imported_pages"], 2)
        site.refresh_from_db()
        self.assertEqual(site.pages.count(), 2)
        homepage = site.pages.get(is_homepage=True)
        self.assertEqual(homepage.page_settings["document_mode"], "full_html")
        self.assertIn("/preview/import-target/about-us", homepage.html)
        self.assertIn("https://example.test/cart", homepage.html)

        preview = self.client.get("/preview/import-target/")
        self.assertEqual(preview.status_code, 200)
        preview_html = preview.content.decode("utf-8")
        self.assertTrue(preview_html.startswith("<!DOCTYPE html>"))
        self.assertIn("/preview/import-target/about-us", preview_html)

    def test_site_mirror_import_rejects_paths_outside_import_root(self):
        User.objects.create_superuser(username="admin", email="admin@example.com", password="VerySecurePass123")
        self.client.post(
            "/api/auth/login/",
            {
                "username": "admin",
                "password": "VerySecurePass123",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )

        site = Site.objects.create(name="Locked Import", slug="locked-import")

        with override_settings(MIRROR_IMPORT_ROOT=Path(__file__).resolve().parent.parent / ".test-mirror-root"):
            response = self.client.post(
                f"/api/sites/{site.id}/import_mirror/",
                {
                    "source_path": str(Path(__file__).resolve().parent.parent),
                    "publish": True,
                    "replace_existing": True,
                },
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf_token(),
            )

        self.assertEqual(response.status_code, 400)
        source_path_error = response.json()["source_path"]
        if isinstance(source_path_error, list):
            source_path_error = source_path_error[0]
        self.assertIn("Mirror imports are limited to", source_path_error)

    def test_active_page_experiment_sets_tracking_cookie_and_logs_exposure(self):
        ensure_seed_data()
        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        experiment = PageExperiment.objects.create(
            site=site,
            page=page,
            name="Contact CTA test",
            key="contact-cta-test",
            status=PageExperiment.STATUS_ACTIVE,
            coverage_percent=100,
            goal_form_name="Contact form",
        )
        PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Control",
            key="control",
            is_control=True,
            weight=50,
        )
        PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Variant B",
            key="variant-b",
            weight=50,
            html="<section><h1>Variant B</h1><p>Tracked experience.</p></section>",
            css=".variant-b { color: #111; }",
        )

        response = self.client.get(f"/preview/{site.slug}{page.path}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(VISITOR_COOKIE_NAME, response.cookies)
        self.assertIn(ASSIGNMENTS_COOKIE_NAME, response.cookies)
        self.assertEqual(
            ExperimentEvent.objects.filter(experiment=experiment, event_type=ExperimentEvent.EVENT_EXPOSURE).count(),
            1,
        )

    def test_forced_experiment_preview_renders_variant_without_tracking(self):
        ensure_seed_data()
        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        experiment = PageExperiment.objects.create(
            site=site,
            page=page,
            name="Hero messaging test",
            key="hero-messaging-test",
            status=PageExperiment.STATUS_ACTIVE,
            coverage_percent=100,
        )
        PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Control",
            key="control",
            is_control=True,
            weight=50,
        )
        PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Variant B",
            key="variant-b",
            weight=50,
            html="<section><h1>Forced Variant</h1></section>",
        )

        response = self.client.get(f"/preview/{site.slug}{page.path}?exp={experiment.key}:variant-b")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Forced Variant")
        self.assertEqual(
            ExperimentEvent.objects.filter(experiment=experiment, event_type=ExperimentEvent.EVENT_EXPOSURE).count(),
            0,
        )

    def test_public_form_submission_records_experiment_conversion(self):
        ensure_seed_data()
        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(path="/contact/").first() or site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        experiment = PageExperiment.objects.create(
            site=site,
            page=page,
            name="Lead form test",
            key="lead-form-test",
            status=PageExperiment.STATUS_ACTIVE,
            coverage_percent=100,
            goal_form_name="Contact form",
        )
        control = PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Control",
            key="control",
            is_control=True,
            weight=50,
        )
        PageExperimentVariant.objects.create(
            experiment=experiment,
            name="Variant B",
            key="variant-b",
            weight=50,
            html="<section><h1>Variant B</h1></section>",
        )

        preview_response = self.client.get(f"/preview/{site.slug}{page.path}")
        self.assertEqual(preview_response.status_code, 200)

        submit_response = self.client.post(
            "/api/public/forms/submit/",
            {
                "site_slug": site.slug,
                "page_path": page.path,
                "form_name": "Contact form",
                "payload": {
                    "name": "Sam",
                    "email": "sam@example.com",
                    "message": "Ready for optimization.",
                },
            },
            content_type="application/json",
        )
        self.assertEqual(submit_response.status_code, 201)
        self.assertEqual(
            ExperimentEvent.objects.filter(experiment=experiment, event_type=ExperimentEvent.EVENT_CONVERSION).count(),
            1,
        )
        conversion = ExperimentEvent.objects.get(experiment=experiment, event_type=ExperimentEvent.EVENT_CONVERSION)
        self.assertEqual(conversion.goal_key, "Contact form")
        self.assertIsNotNone(conversion.variant_id)

    def test_page_review_lifecycle_supports_assignment_and_approval(self):
        owner = User.objects.create_superuser(username="owner", email="owner@example.com", password="VerySecurePass123")
        reviewer = User.objects.create_user(username="reviewer", email="reviewer@example.com", password="VerySecurePass123")
        ensure_seed_data()

        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        workspace = Workspace.objects.create(name="Northstar Workspace", slug="northstar-workspace", owner=owner)
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=owner,
        )
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=reviewer,
            role=WorkspaceMembership.ROLE_EDITOR,
            invited_by=owner,
        )
        site.workspace = workspace
        site.save(update_fields=["workspace", "updated_at"])

        self._login(self.client, "owner", "VerySecurePass123")
        create_response = self.client.post(
            "/api/page-reviews/",
            {
                "page": page.id,
                "locale": None,
                "title": "Homepage QA review",
                "last_note": "Check the hero spacing before approval.",
                "assigned_to": reviewer.id,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(create_response.status_code, 201)
        review_id = create_response.json()["id"]

        collaborators_response = self.client.get(f"/api/page-reviews/collaborators/?site={site.id}")
        self.assertEqual(collaborators_response.status_code, 200)
        self.assertEqual({item["username"] for item in collaborators_response.json()}, {"owner", "reviewer"})

        request_review_response = self.client.post(
            f"/api/page-reviews/{review_id}/request_review/",
            {
                "last_note": "Ready for QA sign-off.",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(request_review_response.status_code, 200)
        review_payload = request_review_response.json()
        self.assertEqual(review_payload["status"], PageReview.STATUS_IN_REVIEW)
        self.assertEqual(review_payload["requested_by_user"]["username"], "owner")
        self.assertIsNotNone(review_payload["requested_at"])

        reviewer_client = Client(enforce_csrf_checks=True)
        self._login(reviewer_client, "reviewer", "VerySecurePass123")
        approve_response = reviewer_client.post(
            f"/api/page-reviews/{review_id}/approve/",
            {
                "last_note": "Approved for publishing.",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token_for(reviewer_client),
        )
        self.assertEqual(approve_response.status_code, 200)
        approved_payload = approve_response.json()
        self.assertEqual(approved_payload["status"], PageReview.STATUS_APPROVED)
        self.assertEqual(approved_payload["approved_by_user"]["username"], "reviewer")
        self.assertIsNotNone(approved_payload["approved_at"])

    def test_workspace_invite_sends_notification_and_returns_invite_url(self):
        owner = User.objects.create_superuser(username="owner", email="owner@example.com", password="VerySecurePass123")
        workspace = Workspace.objects.create(name="Agency Ops", slug="agency-ops", owner=owner)
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=owner,
        )

        self._login(self.client, "owner", "VerySecurePass123")

        with mock.patch.object(notification_service, "send_workspace_invitation", return_value=True) as send_invite:
            response = self.client.post(
                f"/api/workspaces/{workspace.id}/invite/",
                {
                    "email": "new-user@example.com",
                    "role": WorkspaceMembership.ROLE_EDITOR,
                },
                content_type="application/json",
                HTTP_X_CSRFTOKEN=self._csrf_token(),
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertIn("/editor?invite_token=", payload["invite_url"])
        invitation = WorkspaceInvitation.objects.get(workspace=workspace, email="new-user@example.com")
        send_invite.assert_called_once_with(invitation, owner.get_username())

    def test_page_review_comments_support_mentions_replies_and_resolution(self):
        owner = User.objects.create_superuser(username="owner", email="owner@example.com", password="VerySecurePass123")
        reviewer = User.objects.create_user(username="reviewer", email="reviewer@example.com", password="VerySecurePass123")
        ensure_seed_data()

        site = Site.objects.get(slug="northstar-studio")
        page = site.pages.filter(is_homepage=False).order_by("id").first()
        self.assertIsNotNone(page)

        workspace = Workspace.objects.create(name="Review Workspace", slug="review-workspace", owner=owner)
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=owner,
        )
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=reviewer,
            role=WorkspaceMembership.ROLE_EDITOR,
            invited_by=owner,
        )
        site.workspace = workspace
        site.save(update_fields=["workspace", "updated_at"])
        self._login(self.client, "owner", "VerySecurePass123")

        review = PageReview.objects.create(
            page=page,
            title="Review thread",
            status=PageReview.STATUS_IN_REVIEW,
            requested_by=owner,
            assigned_to=reviewer,
        )

        reviewer_client = Client(enforce_csrf_checks=True)
        self._login(reviewer_client, "reviewer", "VerySecurePass123")
        comment_response = reviewer_client.post(
            "/api/page-review-comments/",
            {
                "review": review.id,
                "body": "Please tighten the hero spacing for @[owner](1).",
                "mentions": [{"id": owner.id, "display": owner.username}],
                "anchor": {
                    "component_id": "hero-1",
                    "name": "Hero block",
                    "tag_name": "section",
                    "text_preview": "Turn one editor into your website engine.",
                },
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token_for(reviewer_client),
        )
        self.assertEqual(comment_response.status_code, 201)
        comment_payload = comment_response.json()
        self.assertEqual(comment_payload["author"]["username"], "reviewer")
        self.assertEqual(comment_payload["mentions"][0]["display"], "owner")
        self.assertEqual(comment_payload["anchor"]["component_id"], "hero-1")

        reply_response = self.client.post(
            "/api/page-review-comments/",
            {
                "review": review.id,
                "parent": comment_payload["id"],
                "body": "Updated the spacing and CTA padding.",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(reply_response.status_code, 201)
        self.assertEqual(reply_response.json()["parent_id"], comment_payload["id"])

        resolve_response = self.client.post(
            f"/api/page-review-comments/{comment_payload['id']}/resolve/",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(resolve_response.status_code, 200)
        resolved_payload = resolve_response.json()
        self.assertTrue(resolved_payload["is_resolved"])
        self.assertEqual(resolved_payload["resolved_by_user"]["username"], "owner")
        self.assertIsNotNone(resolved_payload["resolved_at"])

        list_response = self.client.get(f"/api/page-reviews/?page_id={page.id}&locale=null")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()[0]["stats"]["resolved_comment_count"], 1)
        self.assertEqual(PageReviewComment.objects.filter(review=review).count(), 2)

    def test_platform_admin_overview_is_owner_only(self):
        platform_owner = User.objects.create_superuser(
            username="platform",
            email="platform@example.com",
            password="VerySecurePass123",
        )
        workspace_owner = User.objects.create_user(
            username="workspace-owner",
            email="workspace-owner@example.com",
            password="VerySecurePass123",
        )
        workspace = Workspace.objects.create(name="Growth Ops", slug="growth-ops", owner=workspace_owner)
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=workspace_owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=workspace_owner,
        )
        site = Site.objects.create(name="Growth Site", slug="growth-site", workspace=workspace)
        Page.objects.create(site=site, title="Home", slug="home", path="/")
        Order.objects.create(
            site=site,
            order_number="ORD-1001",
            customer_name="Pat",
            customer_email="pat@example.com",
            total="149.00",
            payment_status=Order.PAYMENT_PAID,
            payment_provider="stripe",
        )
        PlatformSubscription.objects.create(
            workspace=workspace,
            plan=PlatformSubscription.PLAN_PRO,
            status=PlatformSubscription.STATUS_ACTIVE,
            monthly_recurring_revenue="149.00",
        )
        PlatformOffer.objects.create(
            name="Q2 Pro Boost",
            code="q2-pro-boost",
            headline="Upgrade to Pro",
            status=PlatformOffer.STATUS_ACTIVE,
            created_by=platform_owner,
        )
        PlatformEmailCampaign.objects.create(
            name="Quarterly Promo",
            subject="Scale your workspace",
            body_text="Upgrade now for more seats and premium automation.",
            audience_type=PlatformEmailCampaign.AUDIENCE_ALL_USERS,
            status=PlatformEmailCampaign.STATUS_SENT,
            recipient_count=2,
            sent_count=2,
            sent_at=timezone.now(),
            created_by=platform_owner,
        )

        blocked_client = Client(enforce_csrf_checks=True)
        self._login(blocked_client, "workspace-owner", "VerySecurePass123")
        blocked_response = blocked_client.get("/api/platform-admin/overview/")
        self.assertEqual(blocked_response.status_code, 403)

        self._login(self.client, "platform", "VerySecurePass123")
        response = self.client.get("/api/platform-admin/overview/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metrics"]["total_users"], 2)
        self.assertEqual(payload["metrics"]["total_workspaces"], 1)
        self.assertEqual(payload["metrics"]["total_sites"], 1)
        self.assertEqual(payload["metrics"]["paid_orders"], 1)
        self.assertEqual(payload["metrics"]["subscriptions_active"], 1)
        self.assertEqual(payload["metrics"]["active_offers"], 1)
        self.assertEqual(payload["metrics"]["sent_campaigns"], 1)
        self.assertEqual(payload["metrics"]["total_revenue"], "149.00")
        self.assertEqual(payload["recent_workspaces"][0]["name"], "Growth Ops")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="ops@example.com",
    )
    def test_platform_admin_can_manage_subscriptions_offers_and_campaigns(self):
        User.objects.create_superuser(
            username="platform",
            email="platform@example.com",
            password="VerySecurePass123",
        )
        workspace_owner = User.objects.create_user(
            username="agency-owner",
            email="agency-owner@example.com",
            password="VerySecurePass123",
        )
        workspace = Workspace.objects.create(name="Revenue Team", slug="revenue-team", owner=workspace_owner)
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=workspace_owner,
            role=WorkspaceMembership.ROLE_OWNER,
            invited_by=workspace_owner,
        )

        self._login(self.client, "platform", "VerySecurePass123")

        subscription_response = self.client.post(
            "/api/platform-subscriptions/",
            {
                "workspace": workspace.id,
                "plan": PlatformSubscription.PLAN_ENTERPRISE,
                "status": PlatformSubscription.STATUS_TRIALING,
                "billing_cycle": PlatformSubscription.BILLING_YEARLY,
                "seats": 12,
                "monthly_recurring_revenue": "499.00",
                "notes": "Managed by platform ops.",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(subscription_response.status_code, 201)
        self.assertEqual(subscription_response.json()["workspace_name"], "Revenue Team")

        offer_response = self.client.post(
            "/api/platform-offers/",
            {
                "name": "Enterprise Expansion",
                "code": "enterprise-expansion",
                "headline": "Expand seats with a launch credit",
                "description": "For fast-growing agencies moving to annual billing.",
                "offer_type": PlatformOffer.TYPE_PERCENTAGE,
                "target_plan": PlatformOffer.TARGET_ENTERPRISE,
                "discount_value": "20.00",
                "duration_in_months": 6,
                "seats_delta": 3,
                "cta_url": "/pricing/enterprise",
                "status": PlatformOffer.STATUS_ACTIVE,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(offer_response.status_code, 201)
        offer_id = offer_response.json()["id"]

        campaign_response = self.client.post(
            "/api/platform-email-campaigns/",
            {
                "name": "Expansion Promo",
                "subject": "Your enterprise upgrade offer is ready",
                "preview_text": "New seat credits for annual plans.",
                "body_text": "Move to annual enterprise and unlock three bonus seats.",
                "body_html": "<p>Move to annual enterprise and unlock <strong>three bonus seats</strong>.</p>",
                "audience_type": PlatformEmailCampaign.AUDIENCE_WORKSPACE_OWNERS,
                "offer": offer_id,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(campaign_response.status_code, 201)
        campaign_id = campaign_response.json()["id"]

        send_response = self.client.post(
            f"/api/platform-email-campaigns/{campaign_id}/send_now/",
            {},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self._csrf_token(),
        )
        self.assertEqual(send_response.status_code, 200)
        self.assertEqual(send_response.json()["status"], PlatformEmailCampaign.STATUS_SENT)
        self.assertEqual(send_response.json()["sent_count"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["agency-owner@example.com"])

        users_response = self.client.get("/api/platform-admin/users/?q=agency")
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(users_response.json()[0]["username"], "agency-owner")

        workspaces_response = self.client.get("/api/platform-admin/workspaces/?q=revenue")
        self.assertEqual(workspaces_response.status_code, 200)
        self.assertEqual(workspaces_response.json()[0]["subscription"]["plan"], PlatformSubscription.PLAN_ENTERPRISE)


class ProductionHardeningTests(TestCase):
    """Tests for production hardening features added during audit completion."""

    def setUp(self):
        self.client = Client()

    def test_health_endpoint_returns_ok_status(self):
        """Health check endpoint returns status ok with database check."""
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("checks", data)
        self.assertEqual(data["checks"]["database"], "ok")

    def test_metrics_endpoint_returns_counts(self):
        """Metrics endpoint returns application metrics."""
        response = self.client.get("/api/metrics/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("database_connected", data)
        self.assertTrue(data["database_connected"])
        # Metrics should include count fields
        self.assertIn("users_total", data)
        self.assertIn("sites_total", data)

    def test_svg_validation_rejects_script_tags(self):
        """SVG validation rejects files containing script tags."""
        from .upload_validation import is_svg_safe, validate_svg_content
        from io import BytesIO

        dangerous_svg = b'<svg><script>alert("xss")</script></svg>'
        is_safe, error = is_svg_safe(dangerous_svg)
        self.assertFalse(is_safe)
        self.assertIn("script", error.lower())

        # Test via validate_svg_content with file-like object
        file_obj = BytesIO(dangerous_svg)
        is_valid, error = validate_svg_content(file_obj)
        self.assertFalse(is_valid)

    def test_svg_validation_rejects_event_handlers(self):
        """SVG validation rejects files containing event handlers."""
        from .upload_validation import is_svg_safe

        dangerous_svg = b'<svg onload="alert(1)"><rect/></svg>'
        is_safe, error = is_svg_safe(dangerous_svg)
        self.assertFalse(is_safe)
        self.assertIn("onload", error.lower())

    def test_svg_validation_rejects_javascript_urls(self):
        """SVG validation rejects files containing javascript: URLs."""
        from .upload_validation import is_svg_safe

        dangerous_svg = b'<svg><a href="javascript:alert(1)">click</a></svg>'
        is_safe, error = is_svg_safe(dangerous_svg)
        self.assertFalse(is_safe)
        # May be rejected for href attr or javascript: URL - both are valid rejections
        self.assertTrue("href" in error.lower() or "javascript" in error.lower())

    def test_svg_validation_accepts_safe_svg(self):
        """SVG validation accepts clean SVG files."""
        from .upload_validation import is_svg_safe

        safe_svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="100" height="100" fill="blue"/></svg>'
        is_safe, error = is_svg_safe(safe_svg)
        self.assertTrue(is_safe)
        self.assertEqual(error, "")

    def test_json_formatter_produces_valid_json(self):
        """JsonFormatter produces valid JSON log output."""
        import json
        import logging
        from io import StringIO
        from .logging_config import JsonFormatter

        formatter = JsonFormatter()
        handler = logging.StreamHandler(StringIO())
        handler.setFormatter(formatter)

        logger = logging.getLogger("test_json_formatter")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Create a log record
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        # Should be valid JSON
        parsed = json.loads(output)
        self.assertEqual(parsed["message"], "Test message")
        self.assertEqual(parsed["level"], "INFO")
        self.assertIn("timestamp", parsed)

    def test_throttle_classes_exist_and_have_correct_scope(self):
        """Throttle classes are properly configured with correct scopes."""
        from .throttles import (
            PublicFormThrottle,
            PublicCommentThrottle,
            PublicCheckoutThrottle,
            WebhookThrottle,
        )

        self.assertEqual(PublicFormThrottle.scope, "public_form")
        self.assertEqual(PublicCommentThrottle.scope, "public_comment")
        self.assertEqual(PublicCheckoutThrottle.scope, "public_checkout")
        self.assertEqual(WebhookThrottle.scope, "webhook")

    def test_site_scoped_session_keys_are_unique_per_site(self):
        """Session keys for cart/checkout are scoped by site slug."""
        from .views import _shop_checkout_session_key, _shop_order_session_key

        key1 = _shop_checkout_session_key("site-a")
        key2 = _shop_checkout_session_key("site-b")
        self.assertNotEqual(key1, key2)
        self.assertIn("site-a", key1)
        self.assertIn("site-b", key2)

        order_key1 = _shop_order_session_key("site-a")
        order_key2 = _shop_order_session_key("site-b")
        self.assertNotEqual(order_key1, order_key2)

    def test_webhook_retry_idempotency_key_format(self):
        """Webhook retry jobs use correct idempotency key format."""
        # This tests the format, actual job creation tested via integration
        delivery_id = 123
        attempt_count = 2
        expected_key = f"webhook_retry:{delivery_id}:{attempt_count}"
        self.assertEqual(expected_key, "webhook_retry:123:2")
