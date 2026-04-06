"""Commerce serializers, including runtime-safe public read payloads."""

from __future__ import annotations

from rest_framework import serializers

from commerce.models import Product, ProductCategory, ProductVariant

from builder.serializers import (  # noqa: F401
    CartItemSerializer,
    CartSerializer,
    DiscountCodeSerializer,
    OrderItemSerializer,
    OrderSerializer,
    PaymentConfigSerializer,
    PaymentIntentResponseSerializer,
    PaymentIntentSerializer,
    ProductCategorySerializer,
    ProductSerializer,
    ProductVariantSerializer,
    PublicCartAddSerializer,
    PublicCartItemUpdateSerializer,
    PublicCartPricingSerializer,
    PublicCheckoutSerializer,
    ShippingRateSerializer,
    ShippingZoneSerializer,
    TaxRateSerializer,
)


class PublicRuntimeProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name", "slug", "description"]


class PublicRuntimeProductVariantSerializer(serializers.ModelSerializer):
    """Product variant payload stripped of internal/private fields."""

    available_for_sale = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "title",
            "sku",
            "price",
            "compare_at_price",
            "is_default",
            "attributes",
            "available_for_sale",
        ]

    def get_available_for_sale(self, obj: ProductVariant) -> bool:
        return bool(not obj.track_inventory or obj.inventory > 0)


class PublicRuntimeProductSerializer(serializers.ModelSerializer):
    """Published product payload for storefront rendering."""

    categories = PublicRuntimeProductCategorySerializer(many=True, read_only=True)
    variants = PublicRuntimeProductVariantSerializer(many=True, read_only=True)
    featured_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "description_html",
            "seo",
            "is_featured",
            "published_at",
            "updated_at",
            "categories",
            "variants",
            "featured_image_url",
        ]

    def get_featured_image_url(self, obj: Product) -> str:
        if not obj.featured_media_id or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        url = obj.featured_media.file.url
        return request.build_absolute_uri(url) if request else url


__all__ = [
    "CartItemSerializer",
    "CartSerializer",
    "DiscountCodeSerializer",
    "OrderItemSerializer",
    "OrderSerializer",
    "PaymentConfigSerializer",
    "PaymentIntentResponseSerializer",
    "PaymentIntentSerializer",
    "ProductCategorySerializer",
    "ProductSerializer",
    "ProductVariantSerializer",
    "PublicCartAddSerializer",
    "PublicCartItemUpdateSerializer",
    "PublicCartPricingSerializer",
    "PublicCheckoutSerializer",
    "ShippingRateSerializer",
    "ShippingZoneSerializer",
    "TaxRateSerializer",
    "PublicRuntimeProductCategorySerializer",
    "PublicRuntimeProductSerializer",
    "PublicRuntimeProductVariantSerializer",
]
