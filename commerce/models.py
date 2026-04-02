"""Commerce app models."""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Site, TimeStampedModel


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


class Product(TimeStampedModel):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    ]

    site = models.ForeignKey(Site, related_name="products", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180)
    excerpt = models.TextField(blank=True)
    description_html = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    featured_media = models.ForeignKey(
        "builder.MediaAsset",
        related_name="product_featured_for",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(ProductCategory, related_name="products", blank=True)
    seo = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_featured = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-is_featured", "-published_at", "title"]
        constraints = [
            models.UniqueConstraint(fields=["site", "slug"], name="commerce_unique_site_product_slug"),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.title}"


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, related_name="variants", on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    sku = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    inventory = models.IntegerField(default=0)
    track_inventory = models.BooleanField(default=True)
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
    session_key = models.CharField(max_length=80)
    currency = models.CharField(max_length=8, default="USD")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    converted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["site", "session_key"],
                condition=models.Q(status="open"),
                name="commerce_unique_open_cart_for_session",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.session_key} ({self.status})"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product_variant = models.ForeignKey(ProductVariant, related_name="cart_items", on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["cart", "product_variant"], name="commerce_unique_cart_variant"),
        ]

    def __str__(self) -> str:
        return f"{self.cart.site.name}: {self.product_variant.title} x {self.quantity}"


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
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, "Pending"),
        (PAYMENT_PAID, "Paid"),
        (PAYMENT_FAILED, "Failed"),
        (PAYMENT_REFUNDED, "Refunded"),
    ]

    site = models.ForeignKey(Site, related_name="orders", on_delete=models.CASCADE)
    order_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING)
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
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    pricing_details = models.JSONField(default=dict, blank=True)
    payment_provider = models.CharField(max_length=80, blank=True)
    payment_reference = models.CharField(max_length=180, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-placed_at"]

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

    class Meta:
        ordering = ["price"]

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
