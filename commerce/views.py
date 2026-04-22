"""Commerce domain views including runtime and storefront APIs."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from builder.payment_services import PaymentConfigurationError, PaymentError, get_stripe_publishable_key
from builder.views import (
    CartViewSet as BuilderCartViewSet,
    DiscountCodeViewSet as BuilderDiscountCodeViewSet,
    OrderViewSet as BuilderOrderViewSet,
    ProductCategoryViewSet as BuilderProductCategoryViewSet,
    ProductVariantViewSet as BuilderProductVariantViewSet,
    ProductViewSet as BuilderProductViewSet,
    PublicCartItemDetailView as BuilderPublicCartItemDetailView,
    PublicCartItemsView as BuilderPublicCartItemsView,
    PublicCartPricingView as BuilderPublicCartPricingView,
    PublicCartView as BuilderPublicCartView,
    PublicCheckoutView as BuilderPublicCheckoutView,
    PublicProductDetailView as BuilderPublicProductDetailView,
    PublicProductListView as BuilderPublicProductListView,
    ShippingRateViewSet as BuilderShippingRateViewSet,
    ShippingZoneViewSet as BuilderShippingZoneViewSet,
    SitePermissionMixin,
    TaxRateViewSet as BuilderTaxRateViewSet,
    _check_checkout_order_access,
    public_shop_cart,
    public_shop_index,
    public_shop_product,
)
from cms.services import public_site_capabilities
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
    ProductCollection,
    ProductMedia,
    ProductVariant,
    Refund,
    Shipment,
    TaxRecord,
)
from commerce.serializers import (
    CheckoutSessionSerializer,
    CommerceEventSerializer,
    CustomerAddressSerializer,
    CustomerSerializer,
    FraudSignalSerializer,
    InventorySerializer,
    OrderAuditLogSerializer,
    OrderSerializer,
    PaymentConfigSerializer,
    PaymentIntentSerializer,
    PaymentSerializer,
    ProductCollectionSerializer,
    ProductMediaSerializer,
    PublicCheckoutCompleteSerializer,
    PublicCheckoutSessionCreateSerializer,
    PublicCommerceEventSerializer,
    PublicRuntimeProductCategorySerializer,
    PublicRuntimeProductSerializer,
    RefundSerializer,
    ShipmentSerializer,
    TaxRecordSerializer,
)
from commerce.services import (
    calculate_pricing,
    capture_fraud_signal,
    create_checkout_session,
    create_order_from_checkout,
    create_payment_intent,
    emit_commerce_event,
    expire_checkout_session,
    get_or_create_cart,
    refund_order,
    send_receipt_email,
)
from core.models import Site
from core.views import PublicRuntimeSiteMixin
from provider.services import providers


ProductViewSet = BuilderProductViewSet
ProductCategoryViewSet = BuilderProductCategoryViewSet
ProductVariantViewSet = BuilderProductVariantViewSet
CartViewSet = BuilderCartViewSet
OrderViewSet = BuilderOrderViewSet
DiscountCodeViewSet = BuilderDiscountCodeViewSet
ShippingZoneViewSet = BuilderShippingZoneViewSet
ShippingRateViewSet = BuilderShippingRateViewSet
TaxRateViewSet = BuilderTaxRateViewSet


class PublicProductListView(BuilderPublicProductListView):
    pass


class PublicProductDetailView(BuilderPublicProductDetailView):
    def get(self, request, site_slug: str, product_slug: str):
        response = super().get(request, site_slug=site_slug, product_slug=product_slug)
        if response.status_code >= 400:
            return response
        product_id = str(response.data.get("id") or "")
        if product_id:
            site = get_object_or_404(Site, slug=site_slug)
            emit_commerce_event(
                site=site,
                event_type=CommerceEvent.EVENT_PRODUCT_VIEW,
                aggregate_type="product",
                aggregate_id=product_id,
                payload={"product_id": product_id, "slug": product_slug},
            )
        return response


class PublicCartView(BuilderPublicCartView):
    pass


class PublicCartPricingView(BuilderPublicCartPricingView):
    pass


class PublicCartItemsView(BuilderPublicCartItemsView):
    def post(self, request, site_slug: str):
        response = super().post(request, site_slug=site_slug)
        if response.status_code >= 400:
            return response
        site = get_object_or_404(Site, slug=site_slug)
        emit_commerce_event(
            site=site,
            event_type=CommerceEvent.EVENT_ADD_TO_CART,
            aggregate_type="cart",
            aggregate_id=str(response.data.get("id") or ""),
            payload={
                "product_slug": request.data.get("product_slug"),
                "variant_id": request.data.get("variant_id"),
                "quantity": request.data.get("quantity", 1),
            },
        )
        return response


class PublicCartItemDetailView(BuilderPublicCartItemDetailView):
    pass


class PublicCheckoutView(BuilderPublicCheckoutView):
    def post(self, request, site_slug: str):
        response = super().post(request, site_slug=site_slug)
        if response.status_code >= 400:
            return response
        site = get_object_or_404(Site, slug=site_slug)
        order_id = response.data.get("id")
        if order_id:
            order = Order.objects.filter(pk=order_id, site=site).first()
            if order:
                try:
                    send_receipt_email(order)
                except Exception:
                    pass
        emit_commerce_event(
            site=site,
            event_type=CommerceEvent.EVENT_PURCHASE,
            aggregate_type="order",
            aggregate_id=str(order_id or ""),
            payload={"order_id": order_id, "order_number": response.data.get("order_number")},
        )
        return response


class ProductCollectionViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProductCollectionSerializer

    def get_queryset(self):
        queryset = ProductCollection.objects.select_related("site").order_by("sort_order", "name")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class ProductMediaViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ProductMediaSerializer
    site_lookup_field = "product__site"

    def get_queryset(self):
        queryset = ProductMedia.objects.select_related("product", "variant", "asset").order_by("position", "id")
        site_id = self.request.query_params.get("site")
        product_id = self.request.query_params.get("product")
        if site_id:
            queryset = queryset.filter(product__site_id=site_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return self.filter_by_site_permission(queryset)


class InventoryViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = InventorySerializer
    site_lookup_field = "variant__product__site"

    def get_queryset(self):
        queryset = Inventory.objects.select_related("variant", "variant__product", "variant__product__site").order_by(
            "-updated_at"
        )
        site_id = self.request.query_params.get("site")
        product_id = self.request.query_params.get("product")
        if site_id:
            queryset = queryset.filter(variant__product__site_id=site_id)
        if product_id:
            queryset = queryset.filter(variant__product_id=product_id)
        return self.filter_by_site_permission(queryset)


class CustomerViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer

    def get_queryset(self):
        queryset = Customer.objects.select_related("site", "user").prefetch_related("addresses").order_by("-updated_at")
        site_id = self.request.query_params.get("site")
        search = (self.request.query_params.get("search") or "").strip()
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone__icontains=search)
            )
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["get"])
    def orders(self, request, pk=None):
        customer = self.get_object()
        queryset = customer.orders.select_related("site").prefetch_related("items").order_by("-placed_at")
        return Response(OrderSerializer(queryset, many=True, context={"request": request}).data)


class CustomerAddressViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = CustomerAddressSerializer
    site_lookup_field = "customer__site"

    def get_queryset(self):
        queryset = CustomerAddress.objects.select_related("customer", "customer__site").order_by("-updated_at")
        site_id = self.request.query_params.get("site")
        customer_id = self.request.query_params.get("customer")
        if site_id:
            queryset = queryset.filter(customer__site_id=site_id)
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return self.filter_by_site_permission(queryset)


class CheckoutSessionViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CheckoutSessionSerializer

    def get_queryset(self):
        queryset = CheckoutSession.objects.select_related("site", "cart", "customer").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        status_filter = self.request.query_params.get("status")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        checkout = self.get_object()
        if checkout.status != CheckoutSession.STATUS_OPEN:
            return Response({"detail": "Checkout session is not open."}, status=status.HTTP_400_BAD_REQUEST)
        expire_checkout_session(checkout)
        checkout.refresh_from_db()
        return Response(CheckoutSessionSerializer(checkout, context={"request": request}).data)


class PaymentViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        queryset = Payment.objects.select_related("site", "order").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        order_id = self.request.query_params.get("order")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        return self.filter_by_site_permission(queryset)


class RefundViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = RefundSerializer

    def get_queryset(self):
        queryset = Refund.objects.select_related("site", "order", "payment").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        order_id = self.request.query_params.get("order")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        return self.filter_by_site_permission(queryset)

    def create(self, request, *args, **kwargs):
        order_id = request.data.get("order")
        if not order_id:
            raise ValidationError({"order": "This field is required."})
        order = get_object_or_404(Order.objects.select_related("site"), pk=order_id)
        self.check_site_edit_permission(order.site)
        amount = request.data.get("amount")
        reason = str(request.data.get("reason") or "")
        try:
            amount_decimal = Decimal(str(amount)) if amount not in (None, "") else None
        except Exception as exc:
            raise ValidationError({"amount": "Amount must be a valid decimal value."}) from exc
        try:
            refund = refund_order(order, amount=amount_decimal, reason=reason, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(refund)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ShipmentViewSet(SitePermissionMixin, viewsets.ModelViewSet):
    serializer_class = ShipmentSerializer

    def get_queryset(self):
        queryset = Shipment.objects.select_related("site", "order", "shipping_rate").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        order_id = self.request.query_params.get("order")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        return self.filter_by_site_permission(queryset)

    @action(detail=True, methods=["post"])
    def mark_shipped(self, request, pk=None):
        shipment = self.get_object()
        shipment.status = Shipment.STATUS_SHIPPED
        shipment.shipped_at = timezone.now()
        shipment.save(update_fields=["status", "shipped_at", "updated_at"])
        if shipment.order.fulfillment_status == Order.FULFILLMENT_UNFULFILLED:
            shipment.order.fulfillment_status = Order.FULFILLMENT_PARTIAL
            shipment.order.save(update_fields=["fulfillment_status", "updated_at"])
        return Response(self.get_serializer(shipment).data)

    @action(detail=True, methods=["post"])
    def mark_delivered(self, request, pk=None):
        shipment = self.get_object()
        shipment.status = Shipment.STATUS_DELIVERED
        shipment.delivered_at = timezone.now()
        shipment.save(update_fields=["status", "delivered_at", "updated_at"])
        order = shipment.order
        if not order.shipments.exclude(status=Shipment.STATUS_DELIVERED).exists():
            order.fulfillment_status = Order.FULFILLMENT_FULFILLED
            order.status = Order.STATUS_FULFILLED
            order.fulfilled_at = timezone.now()
            order.save(update_fields=["fulfillment_status", "status", "fulfilled_at", "updated_at"])
        return Response(self.get_serializer(shipment).data)


class OrderAuditLogViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderAuditLogSerializer
    site_lookup_field = "order__site"

    def get_queryset(self):
        queryset = OrderAuditLog.objects.select_related("order", "order__site", "actor").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        order_id = self.request.query_params.get("order")
        if site_id:
            queryset = queryset.filter(order__site_id=site_id)
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        return self.filter_by_site_permission(queryset)


class CommerceEventViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = CommerceEventSerializer

    def get_queryset(self):
        queryset = CommerceEvent.objects.select_related("site").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        event_type = self.request.query_params.get("event_type")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if event_type:
            queryset = queryset.filter(event_type=event_type)
        return self.filter_by_site_permission(queryset)


class FraudSignalViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = FraudSignalSerializer

    def get_queryset(self):
        queryset = FraudSignal.objects.select_related("site", "order", "checkout_session").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        return self.filter_by_site_permission(queryset)


class TaxRecordViewSet(SitePermissionMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = TaxRecordSerializer

    def get_queryset(self):
        queryset = TaxRecord.objects.select_related("site", "order").order_by("-created_at")
        site_id = self.request.query_params.get("site")
        order_id = self.request.query_params.get("order")
        if site_id:
            queryset = queryset.filter(site_id=site_id)
        if order_id:
            queryset = queryset.filter(order_id=order_id)
        return self.filter_by_site_permission(queryset)


class PaymentConfigView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        serializer = PaymentConfigSerializer(
            {
                "stripe_configured": bool(get_stripe_publishable_key()),
                "publishable_key": get_stripe_publishable_key(),
                "default_provider": "stripe",
            }
        )
        return Response(serializer.data)


class PaymentIntentView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        payload = PaymentIntentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        order = get_object_or_404(Order, pk=payload.validated_data["order_id"])
        try:
            _check_checkout_order_access(request, order)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        try:
            payment = create_payment_intent(order)
        except (PaymentConfigurationError, PaymentError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "client_secret": (payment.payload or {}).get("client_secret", ""),
                "payment_intent_id": payment.provider_payment_id,
                "amount": int(payment.amount * 100),
                "currency": payment.currency.lower(),
                "publishable_key": get_stripe_publishable_key(),
                "idempotency_key": payment.idempotency_key,
            }
        )


class PaymentWebhookView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        if not signature:
            return Response({"detail": "Missing Stripe signature."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            event = providers.payment.process_webhook(payload=request.body, signature=signature)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"received": True, "event": event.get("type", ""), "id": event.get("id", "")})


class OrderPaymentStatusView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request, order_id: int):
        order = get_object_or_404(Order, pk=order_id)
        try:
            _check_checkout_order_access(request, order)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            {
                "order_id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "payment_status": order.payment_status,
                "total": str(order.total),
                "currency": order.currency,
            }
        )


class RefundOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_id: int):
        order = get_object_or_404(Order.objects.select_related("site"), pk=order_id)
        from shared.policies.access import SitePermission, has_site_permission

        if not has_site_permission(request.user, order.site, SitePermission.MANAGE):
            raise PermissionDenied("You don't have permission to refund this order.")
        amount = request.data.get("amount")
        reason = str(request.data.get("reason") or "")
        try:
            amount_decimal = Decimal(str(amount)) if amount not in (None, "") else None
        except Exception as exc:
            raise ValidationError({"amount": "Amount must be a valid decimal value."}) from exc
        try:
            refund = refund_order(order, amount=amount_decimal, reason=reason, actor=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RefundSerializer(refund, context={"request": request}).data)


def _remember_checkout_order(request, order: Order) -> None:
    key = f"wb_shop_orders:{order.site.slug}"
    existing = request.session.get(key, [])
    if order.id not in existing:
        request.session[key] = [*existing, order.id][-20:]
        request.session.modified = True


class PublicCheckoutSessionView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, site_slug: str):
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCheckoutSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = get_or_create_cart(site, request.session)
        try:
            checkout = create_checkout_session(
                cart,
                shipping_address=serializer.validated_data.get("shipping_address") or {},
                billing_address=serializer.validated_data.get("billing_address") or {},
                shipping_rate_id=serializer.validated_data.get("shipping_rate_id"),
                discount_code=serializer.validated_data.get("discount_code", ""),
                email=serializer.validated_data.get("email", ""),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        capture_fraud_signal(
            site=site,
            checkout_session=checkout,
            request=request,
            signal_type="checkout.begin",
            metadata={"session_key": request.session.session_key},
        )
        return Response(CheckoutSessionSerializer(checkout, context={"request": request}).data, status=status.HTTP_201_CREATED)


class PublicCheckoutCompleteView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, site_slug: str):
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCheckoutCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkout = get_object_or_404(
            site.checkout_sessions.select_related("cart"),
            token=serializer.validated_data["checkout_token"],
        )
        try:
            order = create_order_from_checkout(
                checkout,
                customer_name=serializer.validated_data["customer_name"],
                customer_email=serializer.validated_data["customer_email"],
                customer_phone=serializer.validated_data.get("customer_phone", ""),
                notes=serializer.validated_data.get("notes", ""),
                actor=request.user if request.user.is_authenticated else None,
                newsletter_consent=serializer.validated_data.get("newsletter_consent", False),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _remember_checkout_order(request, order)
        try:
            send_receipt_email(order)
        except Exception:
            pass
        return Response(OrderSerializer(order, context={"request": request}).data, status=status.HTTP_201_CREATED)


class PublicShippingRatesView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, site_slug: str):
        site = get_object_or_404(Site, slug=site_slug)
        shipping_address = request.data.get("shipping_address") or {}
        cart = get_or_create_cart(site, request.session)
        rates = providers.shipping.list_rates(site, shipping_address=shipping_address)
        pricing = calculate_pricing(cart, shipping_address=shipping_address)
        tax_details = providers.tax.calculate_tax(
            site,
            shipping_address=shipping_address,
            taxable_subtotal=pricing["subtotal"],
            shipping_total=pricing["shipping_total"],
        )
        return Response(
            {
                "shipping_rates": rates,
                "pricing": {
                    "subtotal": str(pricing["subtotal"]),
                    "shipping_total": str(pricing["shipping_total"]),
                    "tax_total": str(pricing["tax_total"]),
                    "discount_total": str(pricing["discount_total"]),
                    "total": str(pricing["total"]),
                },
                "tax": {
                    "tax_total": str(tax_details.get("tax_total", Decimal("0.00"))),
                    "tax_rate": tax_details.get("tax_rate"),
                },
            }
        )


class PublicCommerceEventTrackView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request, site_slug: str):
        site = get_object_or_404(Site, slug=site_slug)
        serializer = PublicCommerceEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = emit_commerce_event(
            site=site,
            event_type=serializer.validated_data["event"],
            aggregate_type=serializer.validated_data.get("aggregate_type", ""),
            aggregate_id=serializer.validated_data.get("aggregate_id", ""),
            payload=serializer.validated_data.get("payload") or {},
        )
        return Response({"id": event.id, "event_type": event.event_type}, status=status.HTTP_201_CREATED)


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
            .prefetch_related("categories", "collections", variants_prefetch)
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
                | Q(variants__sku__icontains=query)
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
                "collections",
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

        emit_commerce_event(
            site=site,
            event_type=CommerceEvent.EVENT_PRODUCT_VIEW,
            aggregate_type="product",
            aggregate_id=str(product.id),
            payload={"product_id": product.id, "slug": product.slug},
        )
        serializer = PublicRuntimeProductSerializer(product, context={"request": request})
        return Response({"site": {"id": site.id, "slug": site.slug}, "product": serializer.data})


__all__ = [
    "CartViewSet",
    "CheckoutSessionViewSet",
    "CommerceEventViewSet",
    "CustomerAddressViewSet",
    "CustomerViewSet",
    "DiscountCodeViewSet",
    "FraudSignalViewSet",
    "InventoryViewSet",
    "OrderAuditLogViewSet",
    "OrderPaymentStatusView",
    "OrderViewSet",
    "PaymentConfigView",
    "PaymentIntentView",
    "PaymentViewSet",
    "PaymentWebhookView",
    "ProductCategoryViewSet",
    "ProductCollectionViewSet",
    "ProductMediaViewSet",
    "ProductVariantViewSet",
    "ProductViewSet",
    "PublicCartItemDetailView",
    "PublicCartItemsView",
    "PublicCartPricingView",
    "PublicCartView",
    "PublicCheckoutCompleteView",
    "PublicCheckoutSessionView",
    "PublicCheckoutView",
    "PublicCommerceEventTrackView",
    "PublicProductDetailView",
    "PublicProductListView",
    "PublicRuntimeProductCategoriesView",
    "PublicRuntimeProductDetailView",
    "PublicRuntimeProductsView",
    "PublicShippingRatesView",
    "RefundOrderView",
    "RefundViewSet",
    "ShipmentViewSet",
    "ShippingRateViewSet",
    "ShippingZoneViewSet",
    "TaxRateViewSet",
    "TaxRecordViewSet",
    "public_shop_cart",
    "public_shop_index",
    "public_shop_product",
]
