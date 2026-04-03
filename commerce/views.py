"""Commerce domain view wrappers."""

from __future__ import annotations

from builder.views import (
    CartViewSet as BuilderCartViewSet,
    DiscountCodeViewSet as BuilderDiscountCodeViewSet,
    OrderPaymentStatusView as BuilderOrderPaymentStatusView,
    OrderViewSet as BuilderOrderViewSet,
    PaymentConfigView as BuilderPaymentConfigView,
    PaymentIntentView as BuilderPaymentIntentView,
    PaymentWebhookView as BuilderPaymentWebhookView,
    ProductCategoryViewSet as BuilderProductCategoryViewSet,
    ProductVariantViewSet as BuilderProductVariantViewSet,
    ProductViewSet as BuilderProductViewSet,
    PublicCartItemDetailView,
    PublicCartItemsView,
    PublicCartPricingView,
    PublicCartView,
    PublicCheckoutView,
    PublicProductDetailView,
    PublicProductListView,
    RefundOrderView as BuilderRefundOrderView,
    ShippingRateViewSet as BuilderShippingRateViewSet,
    ShippingZoneViewSet as BuilderShippingZoneViewSet,
    TaxRateViewSet as BuilderTaxRateViewSet,
    public_shop_cart,
    public_shop_index,
    public_shop_product,
)


class ProductViewSet(BuilderProductViewSet):
    """Product endpoints."""


class ProductCategoryViewSet(BuilderProductCategoryViewSet):
    """Product category endpoints."""


class ProductVariantViewSet(BuilderProductVariantViewSet):
    """Product variant endpoints."""


class CartViewSet(BuilderCartViewSet):
    """Cart endpoints."""


class OrderViewSet(BuilderOrderViewSet):
    """Order endpoints."""


class DiscountCodeViewSet(BuilderDiscountCodeViewSet):
    """Discount code endpoints."""


class ShippingZoneViewSet(BuilderShippingZoneViewSet):
    """Shipping zone endpoints."""


class ShippingRateViewSet(BuilderShippingRateViewSet):
    """Shipping rate endpoints."""


class TaxRateViewSet(BuilderTaxRateViewSet):
    """Tax rate endpoints."""


class PaymentConfigView(BuilderPaymentConfigView):
    """Checkout config endpoint."""


class PaymentIntentView(BuilderPaymentIntentView):
    """Payment intent endpoint."""


class PaymentWebhookView(BuilderPaymentWebhookView):
    """Payment webhook endpoint."""


class OrderPaymentStatusView(BuilderOrderPaymentStatusView):
    """Order payment status endpoint."""


class RefundOrderView(BuilderRefundOrderView):
    """Order refund endpoint."""


__all__ = [
    "CartViewSet",
    "DiscountCodeViewSet",
    "OrderPaymentStatusView",
    "OrderViewSet",
    "PaymentConfigView",
    "PaymentIntentView",
    "PaymentWebhookView",
    "ProductCategoryViewSet",
    "ProductVariantViewSet",
    "ProductViewSet",
    "PublicCartItemDetailView",
    "PublicCartItemsView",
    "PublicCartPricingView",
    "PublicCartView",
    "PublicCheckoutView",
    "PublicProductDetailView",
    "PublicProductListView",
    "RefundOrderView",
    "ShippingRateViewSet",
    "ShippingZoneViewSet",
    "TaxRateViewSet",
    "public_shop_cart",
    "public_shop_index",
    "public_shop_product",
]
