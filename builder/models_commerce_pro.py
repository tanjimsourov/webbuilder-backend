"""
Pro Commerce Models - Discount Codes and Shipping Zones

Additional models for advanced e-commerce features.
"""

from django.db import models
from django.utils import timezone
from decimal import Decimal


class DiscountCode(models.Model):
    """Discount code for orders."""
    
    TYPE_PERCENTAGE = 'percentage'
    TYPE_FIXED = 'fixed'
    TYPE_FREE_SHIPPING = 'free_shipping'
    TYPE_CHOICES = [
        (TYPE_PERCENTAGE, 'Percentage'),
        (TYPE_FIXED, 'Fixed Amount'),
        (TYPE_FREE_SHIPPING, 'Free Shipping'),
    ]
    
    site = models.ForeignKey('Site', related_name='discount_codes', on_delete=models.CASCADE)
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
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['site', 'code'], name='unique_site_discount_code'),
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
    
    site = models.ForeignKey('Site', related_name='shipping_zones', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    countries = models.JSONField(default=list)  # List of ISO country codes
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.site.name}: {self.name}"


class ShippingRate(models.Model):
    """Shipping rate for a zone."""
    
    zone = models.ForeignKey(ShippingZone, related_name='rates', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)  # e.g., "Standard", "Express"
    method_code = models.CharField(max_length=50)  # e.g., "standard", "express"
    price = models.DecimalField(max_digits=12, decimal_places=2)
    estimated_days_min = models.IntegerField(default=3)
    estimated_days_max = models.IntegerField(default=7)
    active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['price']
    
    def __str__(self):
        return f"{self.zone.name}: {self.name} (${self.price})"


class TaxRate(models.Model):
    """Tax rate for a region."""
    
    site = models.ForeignKey('Site', related_name='tax_rates', on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    rate = models.DecimalField(max_digits=5, decimal_places=4)  # e.g., 0.0825 for 8.25%
    countries = models.JSONField(default=list)  # List of ISO country codes
    states = models.JSONField(default=list, blank=True)  # Optional state/province codes
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
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
