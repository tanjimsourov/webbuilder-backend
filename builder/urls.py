from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .ai_views import AppsCatalogView, AISiteBlueprintApplyView, AISiteBlueprintView, AISuggestionView
from .email_views import (
    EmailDomainViewSet,
    MailboxViewSet,
    MailAliasViewSet,
    EmailProvisioningTaskViewSet,
    EmailDomainCreateView,
    MailboxCreateView,
)
from .platform_admin_views import (
    PlatformAdminOverviewView,
    PlatformAdminUsersView,
    PlatformAdminWorkspacesView,
    PlatformEmailCampaignViewSet,
    PlatformOfferViewSet,
    PlatformSubscriptionViewSet,
    PlatformAdminUserStatusView,
)
from .views import (
    AuthBootstrapView,
    AuthLoginView,
    AuthMagicLoginView,
    AuthLogoutView,
    AuthStatusView,
    HealthCheckView,
    MetricsView,
    BlockTemplateViewSet,
    CartViewSet,
    CommentViewSet,
    DashboardSummaryView,
    DiscountCodeViewSet,
    DomainContactViewSet,
    DomainViewSet,
    FormSubmissionViewSet,
    GSCCallbackView,
    GSCConnectView,
    GSCCredentialUpdateView,
    GSCDisconnectView,
    GSCPropertiesView,
    GSCStatusView,
    GSCSyncView,
    KeywordRankEntryViewSet,
    LibreCrawlStatusView,
    MediaAssetViewSet,
    MediaFolderViewSet,
    NavigationMenuViewSet,
    OrderPaymentStatusView,
    OrderViewSet,
    PayloadCMSStatusView,
    PayloadEcommerceStatusView,
    PageRevisionViewSet,
    PageExperimentViewSet,
    PageReviewCommentViewSet,
    PageReviewViewSet,
    PageTranslationViewSet,
    PageViewSet,
    PaymentConfigView,
    PaymentIntentView,
    PaymentWebhookView,
    PublicCommentSubmissionView,
    PublicCartItemDetailView,
    PublicCartItemsView,
    PublicCartPricingView,
    PublicCartView,
    PublicCheckoutView,
    PublicFormSubmissionView,
    PublicProductDetailView,
    PublicProductListView,
    PostCategoryViewSet,
    PostTagViewSet,
    PostViewSet,
    ProductCategoryViewSet,
    ProductVariantViewSet,
    ProductViewSet,
    RefundOrderView,
    RobotsTxtViewSet,
    SEOAnalyticsViewSet,
    SEOAuditViewSet,
    SEOSettingsViewSet,
    SerpBearStatusView,
    ShippingRateViewSet,
    ShippingZoneViewSet,
    SiteViewSet,
    SiteLocaleViewSet,
    TaxRateViewSet,
    TrackedKeywordViewSet,
    UmamiStatusView,
    URLRedirectViewSet,
    WebhookViewSet,
    WorkspaceSearchView,
)
from .workspace_views import (
    WorkspaceViewSet,
    AcceptInvitationView,
    MyWorkspacesView,
)
from .form_views import (
    FormViewSet,
    PublicFormView,
)


router = DefaultRouter()
router.register("sites", SiteViewSet, basename="site")
router.register("site-locales", SiteLocaleViewSet, basename="site-locale")
router.register("pages", PageViewSet, basename="page")
router.register("page-translations", PageTranslationViewSet, basename="page-translation")
router.register("page-experiments", PageExperimentViewSet, basename="page-experiment")
router.register("page-reviews", PageReviewViewSet, basename="page-review")
router.register("page-review-comments", PageReviewCommentViewSet, basename="page-review-comment")
router.register("revisions", PageRevisionViewSet, basename="revision")
router.register("media", MediaAssetViewSet, basename="media")
router.register("media-folders", MediaFolderViewSet, basename="media-folder")
router.register("post-categories", PostCategoryViewSet, basename="post-category")
router.register("post-tags", PostTagViewSet, basename="post-tag")
router.register("product-categories", ProductCategoryViewSet, basename="product-category")
router.register("discount-codes", DiscountCodeViewSet, basename="discount-code")
router.register("shipping-zones", ShippingZoneViewSet, basename="shipping-zone")
router.register("shipping-rates", ShippingRateViewSet, basename="shipping-rate")
router.register("tax-rates", TaxRateViewSet, basename="tax-rate")
router.register("posts", PostViewSet, basename="post")
router.register("products", ProductViewSet, basename="product")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")
router.register("comments", CommentViewSet, basename="comment")
router.register("submissions", FormSubmissionViewSet, basename="submission")
router.register("carts", CartViewSet, basename="cart")
router.register("orders", OrderViewSet, basename="order")
router.register("block-templates", BlockTemplateViewSet, basename="block-template")
router.register("redirects", URLRedirectViewSet, basename="redirect")
router.register("domain-contacts", DomainContactViewSet, basename="domain-contact")
router.register("domains", DomainViewSet, basename="domain")
router.register("seo-analytics", SEOAnalyticsViewSet, basename="seo-analytics")
router.register("seo-audits", SEOAuditViewSet, basename="seo-audit")
router.register("seo-settings", SEOSettingsViewSet, basename="seo-settings")
router.register("tracked-keywords", TrackedKeywordViewSet, basename="tracked-keyword")
router.register("keyword-ranks", KeywordRankEntryViewSet, basename="keyword-rank")
router.register("navigation-menus", NavigationMenuViewSet, basename="navigation-menu")
router.register("webhooks", WebhookViewSet, basename="webhook")
router.register("robots-txt", RobotsTxtViewSet, basename="robots-txt")
router.register("workspaces", WorkspaceViewSet, basename="workspace")
router.register("forms", FormViewSet, basename="form")
router.register("platform-subscriptions", PlatformSubscriptionViewSet, basename="platform-subscription")
router.register("platform-offers", PlatformOfferViewSet, basename="platform-offer")
router.register("platform-email-campaigns", PlatformEmailCampaignViewSet, basename="platform-email-campaign")
router.register("email-domains", EmailDomainViewSet, basename="email-domain")
router.register("mailboxes", MailboxViewSet, basename="mailbox")
router.register("mail-aliases", MailAliasViewSet, basename="mail-alias")
router.register("email-provisioning-tasks", EmailProvisioningTaskViewSet, basename="email-provisioning-task")

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health-check"),
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("auth/status/", AuthStatusView.as_view(), name="auth-status"),
    path("auth/bootstrap/", AuthBootstrapView.as_view(), name="auth-bootstrap"),
    path("auth/login/", AuthLoginView.as_view(), name="auth-login"),
    path("auth/magic-login/", AuthMagicLoginView.as_view(), name="auth-magic-login"),
    path("auth/logout/", AuthLogoutView.as_view(), name="auth-logout"),
    path("dashboard/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("apps/", AppsCatalogView.as_view(), name="platform-apps"),
    path("ai/suggestions/", AISuggestionView.as_view(), name="ai-suggestions"),
    path("ai/site-blueprint/", AISiteBlueprintView.as_view(), name="ai-site-blueprint"),
    path("ai/site-blueprint/apply/", AISiteBlueprintApplyView.as_view(), name="ai-site-blueprint-apply"),
    path("search/", WorkspaceSearchView.as_view(), name="workspace-search"),
    path("workspaces/my/", MyWorkspacesView.as_view(), name="my-workspaces"),
    path("workspaces/accept-invitation/", AcceptInvitationView.as_view(), name="accept-invitation"),
    path("platform-admin/overview/", PlatformAdminOverviewView.as_view(), name="platform-admin-overview"),
    path("platform-admin/users/", PlatformAdminUsersView.as_view(), name="platform-admin-users"),
    path("platform-admin/workspaces/", PlatformAdminWorkspacesView.as_view(), name="platform-admin-workspaces"),
    path(
        "platform-admin/users/<int:user_id>/<str:action>/",
        PlatformAdminUserStatusView.as_view(),
        name="platform-admin-user-status",
    ),
    path("public/forms/submit/", PublicFormSubmissionView.as_view(), name="public-form-submit"),
    path("public/forms/<slug:site_slug>/<slug:form_slug>/", PublicFormView.as_view(), name="public-form-view"),
    path("public/forms/<slug:site_slug>/<slug:form_slug>/submit/", PublicFormView.as_view(), name="public-form-submit-new"),
    path("public/comments/submit/", PublicCommentSubmissionView.as_view(), name="public-comment-submit"),
    path("public/shop/<slug:site_slug>/products/", PublicProductListView.as_view(), name="public-product-list"),
    path(
        "public/shop/<slug:site_slug>/products/<slug:product_slug>/",
        PublicProductDetailView.as_view(),
        name="public-product-detail",
    ),
    path("public/shop/<slug:site_slug>/cart/", PublicCartView.as_view(), name="public-cart"),
    path("public/shop/<slug:site_slug>/cart/items/", PublicCartItemsView.as_view(), name="public-cart-items"),
    path("public/shop/<slug:site_slug>/cart/pricing/", PublicCartPricingView.as_view(), name="public-cart-pricing"),
    path(
        "public/shop/<slug:site_slug>/cart/items/<int:item_id>/",
        PublicCartItemDetailView.as_view(),
        name="public-cart-item-detail",
    ),
    path("public/shop/<slug:site_slug>/checkout/", PublicCheckoutView.as_view(), name="public-checkout"),
    path("payments/config/", PaymentConfigView.as_view(), name="payment-config"),
    path("payments/intent/", PaymentIntentView.as_view(), name="payment-intent"),
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("payments/status/<int:order_id>/", OrderPaymentStatusView.as_view(), name="payment-status"),
    path("payments/refund/<int:order_id>/", RefundOrderView.as_view(), name="payment-refund"),
    path("seo/librecrawl/status/", LibreCrawlStatusView.as_view(), name="librecrawl-status"),
    path("seo/serpbear/status/", SerpBearStatusView.as_view(), name="serpbear-status"),
    path("analytics/umami/status/", UmamiStatusView.as_view(), name="umami-status"),
    path("cms/payload/status/", PayloadCMSStatusView.as_view(), name="payload-cms-status"),
    path("commerce/payload/status/", PayloadEcommerceStatusView.as_view(), name="payload-ecommerce-status"),
    path("seo/gsc/connect/", GSCConnectView.as_view(), name="gsc-connect"),
    path("seo/gsc/callback/", GSCCallbackView.as_view(), name="gsc-callback"),
    path("seo/gsc/sync/", GSCSyncView.as_view(), name="gsc-sync"),
    path("seo/gsc/disconnect/", GSCDisconnectView.as_view(), name="gsc-disconnect"),
    path("seo/gsc/status/", GSCStatusView.as_view(), name="gsc-status"),
    path("seo/gsc/properties/", GSCPropertiesView.as_view(), name="gsc-properties"),
    path("seo/gsc/credential/", GSCCredentialUpdateView.as_view(), name="gsc-credential"),
    path("email-hosting/domains/create/", EmailDomainCreateView.as_view(), name="email-domain-create"),
    path("email-hosting/mailboxes/create/", MailboxCreateView.as_view(), name="mailbox-create"),
    path("", include(router.urls)),
]
