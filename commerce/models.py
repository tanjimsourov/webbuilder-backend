"""Commerce app models."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from core.models import Site, TimeStampedModel

User = get_user_model()


class ProductCategory(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="product_categories", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "slug"],
                name="commerce_unique_site_product_category_slug",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class ProductCollection(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="product_collections", on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    rules = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "slug"],
                name="commerce_unique_site_product_collection_slug",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.name}"


class Product(TimeStampedModel):
    TYPE_PHYSICAL = "physical"
    TYPE_DIGITAL = "digital"
    TYPE_SERVICE = "service"
    TYPE_CHOICES = [
        (TYPE_PHYSICAL, "Physical"),
        (TYPE_DIGITAL, "Digital"),
        (TYPE_SERVICE, "Service"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_ARCHIVED, "Archived"),
    ]

    site = models.ForeignKey(Site, related_name="products", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    description_html = models.TextField(blank=True)
    product_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_PHYSICAL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        "cms.MediaAsset",
        related_name="product_featured_for",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(ProductCategory, related_name="products", blank=True)
    collections = models.ManyToManyField(ProductCollection, related_name="products", blank=True)
    seo = models.JSONField(default=dict, blank=True)
    seo_title = models.CharField(max_length=280, blank=True)
    seo_description = models.CharField(max_length=500, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    is_featured = models.BooleanField(default=False)
    is_taxable = models.BooleanField(default=True)
    requires_shipping = models.BooleanField(default=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-is_featured", "-published_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="commerce_unique_site_product_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class ProductMedia(TimeStampedModel):
    product = models.ForeignKey(Product, related_name="media_items", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        "ProductVariant",
        related_name="media_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    asset = models.ForeignKey(
        "cms.MediaAsset",
        related_name="product_media_links",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    source_url = models.URLField(max_length=1000, blank=True)
    alt_text = models.CharField(max_length=280, blank=True)
    position = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.product.title} media #{self.pk}"


class ProductVariant(TimeStampedModel):
    INVENTORY_IN_STOCK = "in_stock"
    INVENTORY_LOW_STOCK = "low_stock"
    INVENTORY_OUT_OF_STOCK = "out_of_stock"
    INVENTORY_BACKORDER = "backorder"
    INVENTORY_PREORDER = "preorder"
    INVENTORY_STATE_CHOICES = [
        (INVENTORY_IN_STOCK, "In stock"),
        (INVENTORY_LOW_STOCK, "Low stock"),
        (INVENTORY_OUT_OF_STOCK, "Out of stock"),
        (INVENTORY_BACKORDER, "Backorder"),
        (INVENTORY_PREORDER, "Preorder"),
    ]

    product = models.ForeignKey(Product, related_name="variants", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    sku = models.CharField(max_length=120)
    barcode = models.CharField(max_length=128, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    inventory = models.IntegerField(default=0)
    inventory_state = models.CharField(
        max_length=20,
        choices=INVENTORY_STATE_CHOICES,
        default=INVENTORY_IN_STOCK,
    )
    low_stock_threshold = models.PositiveIntegerField(default=5)
    track_inventory = models.BooleanField(default=True)
    allow_backorder = models.BooleanField(default=False)
    weight_grams = models.IntegerField(default=0)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-is_default", "title"]
        constraints = [
            models.UniqueConstraint(fields=["product", "sku"], name="commerce_unique_product_variant_sku"),
        ]

    def __str__(self) -> str:
        return f"{self.product.title}: {self.title}"

    def refresh_inventory_state(self) -> str:
        if not self.track_inventory:
            return self.INVENTORY_IN_STOCK
        if self.inventory <= 0 and self.allow_backorder:
            return self.INVENTORY_BACKORDER
        if self.inventory <= 0:
            return self.INVENTORY_OUT_OF_STOCK
        if self.inventory <= self.low_stock_threshold:
            return self.INVENTORY_LOW_STOCK
        return self.INVENTORY_IN_STOCK


class Inventory(TimeStampedModel):
    variant = models.OneToOneField(ProductVariant, related_name="inventory_record", on_delete=models.CASCADE)
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.variant.sku}: {self.available} available"

    @property
    def available(self) -> int:
        return max(0, self.on_hand - self.reserved)


class Customer(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="customers", on_delete=models.CASCADE)
    user = models.ForeignKey(User, related_name="commerce_customers", on_delete=models.SET_NULL, null=True, blank=True)
    email = models.EmailField()
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    tags = models.JSONField(default=list, blank=True)
    newsletter_consent = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    last_order_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at", "email"]
        constraints = [
            models.UniqueConstraint(fields=["site", "email"], name="commerce_unique_site_customer_email"),
        ]
        indexes = [
            models.Index(fields=["site", "email"]),
            models.Index(fields=["site", "last_order_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.email}"

    @property
    def full_name(self) -> str:
        return " ".join(part for part in [self.first_name, self.last_name] if part).strip()


class CustomerAddress(TimeStampedModel):
    customer = models.ForeignKey(Customer, related_name="addresses", on_delete=models.CASCADE)
    label = models.CharField(max_length=80, blank=True)
    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    company = models.CharField(max_length=160, blank=True)
    line1 = models.CharField(max_length=220)
    line2 = models.CharField(max_length=220, blank=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=2)
    phone = models.CharField(max_length=40, blank=True)
    is_default_shipping = models.BooleanField(default=False)
    is_default_billing = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-is_default_shipping", "-is_default_billing", "id"]
        indexes = [
            models.Index(fields=["customer", "is_default_shipping"]),
            models.Index(fields=["customer", "is_default_billing"]),
        ]

    def __str__(self) -> str:
        return f"{self.customer.email}: {self.line1}"

    def as_shipping_dict(self) -> dict[str, str]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "company": self.company,
            "line1": self.line1,
            "line2": self.line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "phone": self.phone,
        }


class Cart(TimeStampedModel):
    STATUS_OPEN = "open"
    STATUS_CONVERTED = "converted"
    STATUS_ABANDONED = "abandoned"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_CONVERTED, "Converted"),
        (STATUS_ABANDONED, "Abandoned"),
    ]

    site = models.ForeignKey(Site, related_name="carts", on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, related_name="carts", on_delete=models.SET_NULL, null=True, blank=True)
    session_key = models.CharField(max_length=80)
    currency = models.CharField(max_length=8, default="USD")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_code = models.ForeignKey(
        "DiscountCode",
        related_name="carts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    converted_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "session_key"],
                condition=models.Q(status="open"),
                name="commerce_unique_open_cart_for_session",
            ),
        ]
        indexes = [
            models.Index(fields=["site", "status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.session_key} ({self.status})"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product_variant = models.ForeignKey(ProductVariant, related_name="cart_items", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product_variant"], name="commerce_unique_cart_variant"),
        ]

    def __str__(self) -> str:
        return f"{self.cart.site.name}: {self.product_variant.title} x {self.quantity}"


class CheckoutSession(TimeStampedModel):
    STATUS_OPEN = "open"
    STATUS_COMPLETED = "completed"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    site = models.ForeignKey(Site, related_name="checkout_sessions", on_delete=models.CASCADE)
    cart = models.ForeignKey(Cart, related_name="checkout_sessions", on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, related_name="checkout_sessions", on_delete=models.SET_NULL, null=True, blank=True)
    token = models.CharField(max_length=48, unique=True, default=uuid.uuid4)
    email = models.EmailField(blank=True)
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    shipping_address = models.JSONField(default=dict, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)
    discount_code = models.CharField(max_length=50, blank=True)
    shipping_rate_id = models.IntegerField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pricing_details = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "status", "expires_at"]),
            models.Index(fields=["token", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: checkout {self.token} ({self.status})"


class Order(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_FULFILLED = "fulfilled"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PAID, "Paid"),
        (STATUS_FULFILLED, "Fulfilled"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PAYMENT_PENDING = "pending"
    PAYMENT_PAID = "paid"
    PAYMENT_FAILED = "failed"
    PAYMENT_REFUNDED = "refunded"
    PAYMENT_PARTIALLY_REFUNDED = "partially_refunded"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
        (PAYMENT_PARTIALLY_REFUNDED, "Partially refunded"),
    ]

    FULFILLMENT_UNFULFILLED = "unfulfilled"
    FULFILLMENT_PARTIAL = "partial"
    FULFILLMENT_FULFILLED = "fulfilled"
    FULFILLMENT_CANCELLED = "cancelled"
    FULFILLMENT_STATUS_CHOICES = [
        (FULFILLMENT_UNFULFILLED, "Unfulfilled"),
        (FULFILLMENT_PARTIAL, "Partial"),
        (FULFILLMENT_FULFILLED, "Fulfilled"),
        (FULFILLMENT_CANCELLED, "Cancelled"),
    ]

    SOURCE_STOREFRONT = "storefront"
    SOURCE_ADMIN = "admin"
    SOURCE_API = "api"
    SOURCE_CHOICES = [
        (SOURCE_STOREFRONT, "Storefront"),
        (SOURCE_ADMIN, "Admin"),
        (SOURCE_API, "API"),
    ]

    site = models.ForeignKey(Site, related_name="orders", on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, related_name="orders", on_delete=models.SET_NULL, null=True, blank=True)
    checkout_session = models.ForeignKey(
        CheckoutSession,
        related_name="orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    order_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING)
    fulfillment_status = models.CharField(
        max_length=20,
        choices=FULFILLMENT_STATUS_CHOICES,
        default=FULFILLMENT_UNFULFILLED,
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_STOREFRONT)
    currency = models.CharField(max_length=8, default="USD")
    customer_name = models.CharField(max_length=180)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=40, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)
    shipping_address = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refunds_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pricing_details = models.JSONField(default=dict, blank=True)
    payment_provider = models.CharField(max_length=80, blank=True)
    payment_reference = models.CharField(max_length=180, blank=True)
    fraud_score = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    metadata = models.JSONField(default=dict, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-placed_at"]
        indexes = [
            models.Index(fields=["site", "order_number"]),
            models.Index(fields=["site", "status", "placed_at"]),
            models.Index(fields=["site", "payment_status", "placed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.order_number}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="order_items", on_delete=models.SET_NULL, null=True, blank=True)
    product_variant = models.ForeignKey(
        ProductVariant,
        related_name="order_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=180)
    sku = models.CharField(max_length=120)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.order.order_number}: {self.title}"


class DiscountCode(models.Model):
    """Discount code for orders."""

    TYPE_PERCENTAGE = "percentage"
    TYPE_FIXED = "fixed"
    TYPE_FREE_SHIPPING = "free_shipping"
    TYPE_CHOICES = [
        (TYPE_PERCENTAGE, "Percentage"),
        (TYPE_FIXED, "Fixed Amount"),
        (TYPE_FREE_SHIPPING, "Free Shipping"),
    ]

    site = models.ForeignKey(Site, related_name="discount_codes", on_delete=models.CASCADE)
    code = models.CharField(max_length=50)
    discount_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    min_purchase = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_uses = models.IntegerField(null=True, blank=True)
    use_count = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    applies_to_collections = models.ManyToManyField(ProductCollection, related_name="discount_codes", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="commerce_unique_site_discount_code"),
        ]

    def __str__(self):
        return f"{self.site.name}: {self.code}"

    def is_valid(self, cart_total: Decimal = None) -> tuple[bool, str]:
        """Check if discount code is valid."""
        if not self.active:
            return False, "Discount code is inactive"

        now = timezone.now()
        if now < self.starts_at:
            return False, "Discount code not yet active"

        if self.expires_at and now > self.expires_at:
            return False, "Discount code has expired"

        if self.max_uses and self.use_count >= self.max_uses:
            return False, "Discount code has reached maximum uses"

        if cart_total and cart_total < self.min_purchase:
            return False, f"Minimum purchase of ${self.min_purchase} required"

        return True, "Valid"


class ShippingZone(models.Model):
    """Shipping zone with rates."""

    site = models.ForeignKey(Site, related_name="shipping_zones", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    countries = models.JSONField(default=list)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name"],
                name="commerce_unique_site_shipping_zone_name",
            ),
        ]

    def __str__(self):
        return f"{self.site.name}: {self.name}"


class ShippingRate(models.Model):
    """Shipping rate for a zone."""

    zone = models.ForeignKey(ShippingZone, related_name="rates", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    method_code = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    estimated_days_min = models.IntegerField(default=3)
    estimated_days_max = models.IntegerField(default=7)
    active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["price"]
        constraints = [
            models.UniqueConstraint(
                fields=["zone", "method_code"],
                name="commerce_unique_shipping_rate_method_code",
            ),
        ]

    def __str__(self):
        return f"{self.zone.name}: {self.name} (${self.price})"


class TaxRate(models.Model):
    """Tax rate for a region."""

    site = models.ForeignKey(Site, related_name="tax_rates", on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=5, decimal_places=4)
    countries = models.JSONField(default=list)
    states = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.site.name}: {self.name} ({self.rate * 100}%)"

    def applies_to(self, country_code: str, state_code: str = None) -> bool:
        """Check if tax rate applies to location."""
        if not self.active:
            return False

        country_match = country_code.upper() in [c.upper() for c in self.countries]

        if not self.states:
            return country_match

        state_match = state_code and state_code.upper() in [s.upper() for s in self.states]
        return country_match and state_match


class Payment(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_PARTIALLY_REFUNDED = "partially_refunded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
        (STATUS_PARTIALLY_REFUNDED, "Partially refunded"),
    ]

    site = models.ForeignKey(Site, related_name="payments", on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="payments", on_delete=models.CASCADE)
    provider = models.CharField(max_length=80, default="stripe")
    provider_payment_id = models.CharField(max_length=180, blank=True)
    idempotency_key = models.CharField(max_length=120, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "provider", "provider_payment_id"],
                name="commerce_unique_provider_payment_per_site",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number}: {self.provider} ({self.status})"


class Refund(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    ]

    site = models.ForeignKey(Site, related_name="refunds", on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="refunds", on_delete=models.CASCADE)
    payment = models.ForeignKey(Payment, related_name="refunds", on_delete=models.SET_NULL, null=True, blank=True)
    provider_refund_id = models.CharField(max_length=180, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    reason = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    metadata = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number}: refund {self.amount} ({self.status})"


class Shipment(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SHIPPED, "Shipped"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    site = models.ForeignKey(Site, related_name="shipments", on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="shipments", on_delete=models.CASCADE)
    shipping_rate = models.ForeignKey(
        ShippingRate,
        related_name="shipments",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    provider = models.CharField(max_length=80, blank=True)
    carrier = models.CharField(max_length=120, blank=True)
    service_level = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=180, blank=True)
    tracking_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number}: shipment ({self.status})"


class TaxRecord(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="tax_records", on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="tax_records", on_delete=models.CASCADE)
    provider = models.CharField(max_length=80, default="internal")
    jurisdiction = models.CharField(max_length=180, blank=True)
    rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=8, default="USD")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "order", "provider"]),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number}: tax {self.tax_amount}"


class StockReservation(TimeStampedModel):
    STATUS_RESERVED = "reserved"
    STATUS_COMMITTED = "committed"
    STATUS_RELEASED = "released"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reserved"),
        (STATUS_COMMITTED, "Committed"),
        (STATUS_RELEASED, "Released"),
        (STATUS_EXPIRED, "Expired"),
    ]

    site = models.ForeignKey(Site, related_name="stock_reservations", on_delete=models.CASCADE)
    product_variant = models.ForeignKey(
        ProductVariant,
        related_name="stock_reservations",
        on_delete=models.CASCADE,
    )
    cart = models.ForeignKey(Cart, related_name="stock_reservations", on_delete=models.SET_NULL, null=True, blank=True)
    checkout_session = models.ForeignKey(
        CheckoutSession,
        related_name="stock_reservations",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    order = models.ForeignKey(Order, related_name="stock_reservations", on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RESERVED)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "status", "expires_at"]),
            models.Index(fields=["product_variant", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_variant.sku}: {self.quantity} ({self.status})"


class OrderAuditLog(TimeStampedModel):
    order = models.ForeignKey(Order, related_name="audit_logs", on_delete=models.CASCADE)
    actor = models.ForeignKey(User, related_name="commerce_audit_logs", on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=80)
    message = models.CharField(max_length=280, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "action", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order.order_number}: {self.action}"


class CommerceEvent(TimeStampedModel):
    EVENT_PRODUCT_VIEW = "product.view"
    EVENT_ADD_TO_CART = "cart.add"
    EVENT_BEGIN_CHECKOUT = "checkout.begin"
    EVENT_PURCHASE = "order.purchase"
    EVENT_REFUND = "order.refund"
    EVENT_CHOICES = [
        (EVENT_PRODUCT_VIEW, "Product view"),
        (EVENT_ADD_TO_CART, "Add to cart"),
        (EVENT_BEGIN_CHECKOUT, "Begin checkout"),
        (EVENT_PURCHASE, "Purchase"),
        (EVENT_REFUND, "Refund"),
    ]

    site = models.ForeignKey(Site, related_name="commerce_events", on_delete=models.CASCADE)
    event_type = models.CharField(max_length=60, choices=EVENT_CHOICES)
    aggregate_type = models.CharField(max_length=60, blank=True)
    aggregate_id = models.CharField(max_length=120, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.event_type}"


class FraudSignal(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="fraud_signals", on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="fraud_signals", on_delete=models.SET_NULL, null=True, blank=True)
    checkout_session = models.ForeignKey(
        CheckoutSession,
        related_name="fraud_signals",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    email = models.EmailField(blank=True)
    signal_type = models.CharField(max_length=80, default="generic")
    score = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["site", "signal_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.signal_type}"
