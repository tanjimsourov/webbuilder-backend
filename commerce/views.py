"""Commerce domain views including headless runtime read endpoints."""

from __future__ import annotations

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

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
from cms.services import public_site_capabilities
from commerce.models import Product, ProductVariant
from commerce.serializers import PublicRuntimeProductCategorySerializer, PublicRuntimeProductSerializer
from core.views import PublicRuntimeSiteMixin


ProductViewSet = BuilderProductViewSet
ProductCategoryViewSet = BuilderProductCategoryViewSet
ProductVariantViewSet = BuilderProductVariantViewSet
CartViewSet = BuilderCartViewSet
OrderViewSet = BuilderOrderViewSet
DiscountCodeViewSet = BuilderDiscountCodeViewSet
ShippingZoneViewSet = BuilderShippingZoneViewSet
ShippingRateViewSet = BuilderShippingRateViewSet
TaxRateViewSet = BuilderTaxRateViewSet
PaymentConfigView = BuilderPaymentConfigView
PaymentIntentView = BuilderPaymentIntentView
PaymentWebhookView = BuilderPaymentWebhookView
OrderPaymentStatusView = BuilderOrderPaymentStatusView
RefundOrderView = BuilderRefundOrderView


class PublicRuntimeProductCategoriesView(PublicRuntimeSiteMixin, APIView):
    """Published category listing endpoint for headless storefront runtime."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("commerce_enabled", False):
            return Response({"site": {"id": site.id, "slug": site.slug}, "results": []})

        categories = (
            site.product_categories.filter(products__status=Product.STATUS_PUBLISHED)
            .filter(Q(products__published_at__isnull=True) | Q(products__published_at__lte=timezone.now()))
            .distinct()
            .order_by("name")
        )
        serializer = PublicRuntimeProductCategorySerializer(categories, many=True)
        return Response({"site": {"id": site.id, "slug": site.slug}, "results": serializer.data})


class PublicRuntimeProductsView(PublicRuntimeSiteMixin, APIView):
    """Published product listing endpoint for headless storefront runtime."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("commerce_enabled", False):
            return Response({"site": {"id": site.id, "slug": site.slug}, "results": []})

        now = timezone.now()
        variants_prefetch = Prefetch(
            "variants",
            queryset=ProductVariant.objects.filter(is_active=True).order_by("-is_default", "title"),
        )
        queryset = (
            site.products.select_related("featured_media")
            .prefetch_related("categories", variants_prefetch)
            .filter(status=Product.STATUS_PUBLISHED)
            .filter(Q(published_at__isnull=True) | Q(published_at__lte=now))
            .order_by("-is_featured", "-published_at", "title")
        )

        category_slug = (request.query_params.get("category") or "").strip()
        query = (request.query_params.get("q") or "").strip()
        if category_slug:
            queryset = queryset.filter(categories__slug=category_slug)
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(excerpt__icontains=query)
                | Q(description_html__icontains=query)
            )
        if (request.query_params.get("featured") or "").strip().lower() in {"1", "true", "yes"}:
            queryset = queryset.filter(is_featured=True)

        try:
            limit = max(1, min(int(request.query_params.get("limit", 24)), 100))
        except (TypeError, ValueError):
            limit = 24

        products = list(queryset[:limit])
        serializer = PublicRuntimeProductSerializer(products, many=True, context={"request": request})
        return Response(
            {
                "site": {"id": site.id, "slug": site.slug},
                "count": len(products),
                "results": serializer.data,
            }
        )


class PublicRuntimeProductDetailView(PublicRuntimeSiteMixin, APIView):
    """Published single-product endpoint for headless storefront runtime."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, product_slug: str):
        site, _ = self.resolve_public_site(request)
        capabilities = public_site_capabilities(site)
        if not capabilities.get("commerce_enabled", False):
            return Response({"detail": "Storefront is disabled for this site."}, status=404)

        now = timezone.now()
        product = get_object_or_404(
            site.products.select_related("featured_media").prefetch_related(
                "categories",
                Prefetch(
                    "variants",
                    queryset=ProductVariant.objects.filter(is_active=True).order_by("-is_default", "title"),
                ),
            ),
            slug=product_slug,
            status=Product.STATUS_PUBLISHED,
        )
        if product.published_at and product.published_at > now:
            return Response({"detail": "Published product not found."}, status=404)

        serializer = PublicRuntimeProductSerializer(product, context={"request": request})
        return Response({"site": {"id": site.id, "slug": site.slug}, "product": serializer.data})


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
    "PublicRuntimeProductCategoriesView",
    "PublicRuntimeProductDetailView",
    "PublicRuntimeProductsView",
    "RefundOrderView",
    "ShippingRateViewSet",
    "ShippingZoneViewSet",
    "TaxRateViewSet",
    "public_shop_cart",
    "public_shop_index",
    "public_shop_product",
]
