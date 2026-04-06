"""Commerce domain API routes."""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import SimpleRouter

from commerce.views import (
    CartViewSet,
    DiscountCodeViewSet,
    OrderPaymentStatusView,
    OrderViewSet,
    PaymentIntentView,
    PaymentWebhookView,
    ProductCategoryViewSet,
    ProductVariantViewSet,
    ProductViewSet,
    PublicCartItemDetailView,
    PublicCartItemsView,
    PublicCartPricingView,
    PublicCartView,
    PublicCheckoutView,
    PublicProductDetailView,
    PublicProductListView,
    PublicRuntimeProductCategoriesView,
    PublicRuntimeProductDetailView,
    PublicRuntimeProductsView,
    RefundOrderView,
    ShippingRateViewSet,
    ShippingZoneViewSet,
    TaxRateViewSet,
)

router = SimpleRouter()
router.register("product-categories", ProductCategoryViewSet, basename="product-category")
router.register("discount-codes", DiscountCodeViewSet, basename="discount-code")
router.register("shipping-zones", ShippingZoneViewSet, basename="shipping-zone")
router.register("shipping-rates", ShippingRateViewSet, basename="shipping-rate")
router.register("tax-rates", TaxRateViewSet, basename="tax-rate")
router.register("products", ProductViewSet, basename="product")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")
router.register("carts", CartViewSet, basename="cart")
router.register("orders", OrderViewSet, basename="order")

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

