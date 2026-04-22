"""Commerce serializers, including runtime-safe public read payloads."""

from __future__ import annotations

from decimal import Decimal

from django.utils.text import slugify
from rest_framework import serializers

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
from commerce.models import (
    CheckoutSession,
    CommerceEvent,
    Customer,
    CustomerAddress,
    FraudSignal,
    Inventory,
    Order,
    OrderAuditLog,
    Payment,
    Product,
    ProductCategory,
    ProductCollection,
    ProductMedia,
    ProductVariant,
    Refund,
    Shipment,
    TaxRecord,
)


class ProductCollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCollection
        fields = [
            "id",
            "site",
            "name",
            "slug",
            "description",
            "is_active",
            "sort_order",
            "rules",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        site = attrs.get("site") or getattr(self.instance, "site", None)
        slug = slugify(attrs.get("slug") or attrs.get("name") or getattr(self.instance, "name", "collection")) or "collection"
        attrs["slug"] = slug
        queryset = ProductCollection.objects.filter(site=site, slug=slug)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError({"slug": "Another collection already uses this slug."})
        return attrs


class ProductMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductMedia
        fields = [
            "id",
            "product",
            "variant",
            "asset",
            "source_url",
            "alt_text",
            "position",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        product = attrs.get("product") or getattr(self.instance, "product", None)
        variant = attrs.get("variant") or getattr(self.instance, "variant", None)
        asset = attrs.get("asset") or getattr(self.instance, "asset", None)
        if variant and product and variant.product_id != product.id:
            raise serializers.ValidationError({"variant": "Variant must belong to the selected product."})
        if asset and product and asset.site_id != product.site_id:
            raise serializers.ValidationError({"asset": "Asset must belong to the same site as the product."})
        return attrs


class InventorySerializer(serializers.ModelSerializer):
    variant_id = serializers.IntegerField(source="variant.id", read_only=True)
    sku = serializers.CharField(source="variant.sku", read_only=True)
    title = serializers.CharField(source="variant.title", read_only=True)
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "variant_id",
            "sku",
            "title",
            "on_hand",
            "reserved",
            "available",
            "low_stock_threshold",
            "metadata",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        on_hand = attrs.get("on_hand", getattr(self.instance, "on_hand", 0))
        reserved = attrs.get("reserved", getattr(self.instance, "reserved", 0))
        if reserved < 0:
            raise serializers.ValidationError({"reserved": "Reserved inventory cannot be negative."})
        if on_hand < reserved:
            raise serializers.ValidationError({"on_hand": "On-hand inventory cannot be less than reserved inventory."})
        return attrs


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = [
            "id",
            "customer",
            "label",
            "first_name",
            "last_name",
            "company",
            "line1",
            "line2",
            "city",
            "state",
            "postal_code",
            "country",
            "phone",
            "is_default_shipping",
            "is_default_billing",
            "metadata",
            "created_at",
            "updated_at",
        ]


class CustomerSerializer(serializers.ModelSerializer):
    addresses = CustomerAddressSerializer(many=True, read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "site",
            "user",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "tags",
            "newsletter_consent",
            "metadata",
            "last_order_at",
            "addresses",
            "created_at",
            "updated_at",
        ]

    def validate_email(self, value):
        return (value or "").strip().lower()


class CheckoutSessionSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = CheckoutSession
        fields = [
            "id",
            "site",
            "cart",
            "customer",
            "token",
            "email",
            "currency",
            "status",
            "shipping_address",
            "billing_address",
            "discount_code",
            "shipping_rate_id",
            "subtotal",
            "shipping_total",
            "tax_total",
            "discount_total",
            "total",
            "pricing_details",
            "expires_at",
            "completed_at",
            "metadata",
            "item_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "token",
            "subtotal",
            "shipping_total",
            "tax_total",
            "discount_total",
            "total",
            "pricing_details",
            "item_count",
            "completed_at",
        ]

    def get_item_count(self, obj: CheckoutSession) -> int:
        return sum(item.quantity for item in obj.cart.items.all())


class PaymentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "site",
            "order",
            "order_number",
            "provider",
            "provider_payment_id",
            "idempotency_key",
            "amount",
            "currency",
            "status",
            "error_code",
            "error_message",
            "payload",
            "processed_at",
            "created_at",
            "updated_at",
        ]


class RefundSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Refund
        fields = [
            "id",
            "site",
            "order",
            "order_number",
            "payment",
            "provider_refund_id",
            "amount",
            "currency",
            "reason",
            "status",
            "metadata",
            "processed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["provider_refund_id", "status", "processed_at"]

    def validate_amount(self, value: Decimal):
        if value <= 0:
            raise serializers.ValidationError("Refund amount must be greater than zero.")
        return value


class ShipmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "site",
            "order",
            "order_number",
            "shipping_rate",
            "provider",
            "carrier",
            "service_level",
            "tracking_number",
            "tracking_url",
            "status",
            "shipped_at",
            "delivered_at",
            "metadata",
            "created_at",
            "updated_at",
        ]


class TaxRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRecord
        fields = [
            "id",
            "site",
            "order",
            "provider",
            "jurisdiction",
            "rate",
            "taxable_amount",
            "tax_amount",
            "currency",
            "payload",
            "created_at",
            "updated_at",
        ]


class OrderAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderAuditLog
        fields = [
            "id",
            "order",
            "actor",
            "action",
            "message",
            "request_id",
            "metadata",
            "created_at",
            "updated_at",
        ]


class CommerceEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommerceEvent
        fields = [
            "id",
            "site",
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "request_id",
            "payload",
            "created_at",
            "updated_at",
        ]


class FraudSignalSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudSignal
        fields = [
            "id",
            "site",
            "order",
            "checkout_session",
            "ip_address",
            "user_agent",
            "email",
            "signal_type",
            "score",
            "metadata",
            "created_at",
            "updated_at",
        ]


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
        return bool(not obj.track_inventory or obj.inventory > 0 or obj.allow_backorder)


class PublicRuntimeProductCollectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCollection
        fields = ["id", "name", "slug", "description", "sort_order"]


class PublicRuntimeProductSerializer(serializers.ModelSerializer):
    """Published product payload for storefront rendering."""

    categories = PublicRuntimeProductCategorySerializer(many=True, read_only=True)
    collections = PublicRuntimeProductCollectionSerializer(many=True, read_only=True)
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
            "product_type",
            "seo",
            "seo_title",
            "seo_description",
            "is_featured",
            "published_at",
            "updated_at",
            "categories",
            "collections",
            "variants",
            "featured_image_url",
        ]

    def get_featured_image_url(self, obj: Product) -> str:
        if not obj.featured_media_id or not obj.featured_media.file:
            return ""
        request = self.context.get("request")
        url = obj.featured_media.file.url
        return request.build_absolute_uri(url) if request else url


class PublicCheckoutSessionCreateSerializer(serializers.Serializer):
    shipping_address = serializers.JSONField(required=False)
    billing_address = serializers.JSONField(required=False)
    shipping_rate_id = serializers.IntegerField(required=False, min_value=1)
    discount_code = serializers.CharField(required=False, allow_blank=True, max_length=50)
    email = serializers.EmailField(required=False, allow_blank=True)


class PublicCheckoutCompleteSerializer(serializers.Serializer):
    checkout_token = serializers.CharField(max_length=64)
    customer_name = serializers.CharField(max_length=180)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(required=False, allow_blank=True, max_length=40)
    notes = serializers.CharField(required=False, allow_blank=True)
    newsletter_consent = serializers.BooleanField(required=False, default=False)


class PublicCommerceEventSerializer(serializers.Serializer):
    event = serializers.ChoiceField(
        choices=[
            CommerceEvent.EVENT_PRODUCT_VIEW,
            CommerceEvent.EVENT_ADD_TO_CART,
            CommerceEvent.EVENT_BEGIN_CHECKOUT,
            CommerceEvent.EVENT_PURCHASE,
            CommerceEvent.EVENT_REFUND,
        ]
    )
    aggregate_type = serializers.CharField(required=False, allow_blank=True, max_length=60)
    aggregate_id = serializers.CharField(required=False, allow_blank=True, max_length=120)
    payload = serializers.JSONField(required=False)


__all__ = [
    "CartItemSerializer",
    "CartSerializer",
    "CheckoutSessionSerializer",
    "CommerceEventSerializer",
    "CustomerAddressSerializer",
    "CustomerSerializer",
    "DiscountCodeSerializer",
    "FraudSignalSerializer",
    "InventorySerializer",
    "OrderAuditLogSerializer",
    "OrderItemSerializer",
    "OrderSerializer",
    "PaymentConfigSerializer",
    "PaymentIntentResponseSerializer",
    "PaymentIntentSerializer",
    "PaymentSerializer",
    "ProductCategorySerializer",
    "ProductCollectionSerializer",
    "ProductMediaSerializer",
    "ProductSerializer",
    "ProductVariantSerializer",
    "PublicCartAddSerializer",
    "PublicCartItemUpdateSerializer",
    "PublicCartPricingSerializer",
    "PublicCheckoutCompleteSerializer",
    "PublicCheckoutSerializer",
    "PublicCheckoutSessionCreateSerializer",
    "PublicCommerceEventSerializer",
    "PublicRuntimeProductCategorySerializer",
    "PublicRuntimeProductCollectionSerializer",
    "PublicRuntimeProductSerializer",
    "PublicRuntimeProductVariantSerializer",
    "RefundSerializer",
    "ShipmentSerializer",
    "ShippingRateSerializer",
    "ShippingZoneSerializer",
    "TaxRateSerializer",
    "TaxRecordSerializer",
]
