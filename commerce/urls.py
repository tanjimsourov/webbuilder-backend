"""Commerce domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from commerce.views import (
    CartViewSet,
    CheckoutSessionViewSet,
    CommerceEventViewSet,
    CustomerAddressViewSet,
    CustomerViewSet,
    DiscountCodeViewSet,
    FraudSignalViewSet,
    InventoryViewSet,
    OrderAuditLogViewSet,
    OrderPaymentStatusView,
    OrderViewSet,
    PaymentConfigView,
    PaymentIntentView,
    PaymentViewSet,
    PaymentWebhookView,
    ProductCategoryViewSet,
    ProductCollectionViewSet,
    ProductMediaViewSet,
    ProductVariantViewSet,
    ProductViewSet,
    PublicCartItemDetailView,
    PublicCartItemsView,
    PublicCartPricingView,
    PublicCartView,
    PublicCheckoutCompleteView,
    PublicCheckoutSessionView,
    PublicCheckoutView,
    PublicCommerceEventTrackView,
    PublicProductDetailView,
    PublicProductListView,
    PublicRuntimeProductCategoriesView,
    PublicRuntimeProductDetailView,
    PublicRuntimeProductsView,
    PublicShippingRatesView,
    RefundOrderView,
    RefundViewSet,
    ShipmentViewSet,
    ShippingRateViewSet,
    ShippingZoneViewSet,
    TaxRateViewSet,
    TaxRecordViewSet,
)

router = SimpleRouter()
router.register("product-categories", ProductCategoryViewSet, basename="product-category")
router.register("product-collections", ProductCollectionViewSet, basename="product-collection")
router.register("product-media", ProductMediaViewSet, basename="product-media")
router.register("discount-codes", DiscountCodeViewSet, basename="discount-code")
router.register("shipping-zones", ShippingZoneViewSet, basename="shipping-zone")
router.register("shipping-rates", ShippingRateViewSet, basename="shipping-rate")
router.register("tax-rates", TaxRateViewSet, basename="tax-rate")
router.register("products", ProductViewSet, basename="product")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")
router.register("inventory", InventoryViewSet, basename="inventory")
router.register("customers", CustomerViewSet, basename="customer")
router.register("customer-addresses", CustomerAddressViewSet, basename="customer-address")
router.register("carts", CartViewSet, basename="cart")
router.register("orders", OrderViewSet, basename="order")
router.register("checkout-sessions", CheckoutSessionViewSet, basename="checkout-session")
router.register("payments", PaymentViewSet, basename="payment")
router.register("refunds", RefundViewSet, basename="refund")
router.register("shipments", ShipmentViewSet, basename="shipment")
router.register("tax-records", TaxRecordViewSet, basename="tax-record")
router.register("order-audit-logs", OrderAuditLogViewSet, basename="order-audit")
router.register("events", CommerceEventViewSet, basename="commerce-event")
router.register("fraud-signals", FraudSignalViewSet, basename="fraud-signal")

urlpatterns = [
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
    path(
        "public/shop/<slug:site_slug>/checkout/session/",
        PublicCheckoutSessionView.as_view(),
        name="public-checkout-session",
    ),
    path(
        "public/shop/<slug:site_slug>/checkout/complete/",
        PublicCheckoutCompleteView.as_view(),
        name="public-checkout-complete",
    ),
    path(
        "public/shop/<slug:site_slug>/shipping-rates/",
        PublicShippingRatesView.as_view(),
        name="public-shipping-rates",
    ),
    path(
        "public/shop/<slug:site_slug>/events/",
        PublicCommerceEventTrackView.as_view(),
        name="public-commerce-event-track",
    ),
    path("payments/config/", PaymentConfigView.as_view(), name="payment-config"),
    path("payments/intent/", PaymentIntentView.as_view(), name="payment-intent"),
    path("payments/webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("payments/status/<int:order_id>/", OrderPaymentStatusView.as_view(), name="payment-status"),
    path("payments/refund/<int:order_id>/", RefundOrderView.as_view(), name="payment-refund"),
    path(
        "public/runtime/commerce/categories/",
        PublicRuntimeProductCategoriesView.as_view(),
        name="runtime-product-categories",
    ),
    path("public/runtime/commerce/products/", PublicRuntimeProductsView.as_view(), name="runtime-products"),
    path(
        "public/runtime/commerce/products/<slug:product_slug>/",
        PublicRuntimeProductDetailView.as_view(),
        name="runtime-product-detail",
    ),
    path("", include(router.urls)),
]

