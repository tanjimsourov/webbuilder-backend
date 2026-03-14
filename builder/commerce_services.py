"""
Commerce Services - Advanced E-commerce Features

Provides shipping zones, tax calculation, discount codes, and inventory alerts.
Inspired by Medusa patterns but adapted to our Django stack.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from django.utils import timezone

logger = logging.getLogger(__name__)


class ShippingZone:
    """Shipping zone with rates."""
    
    def __init__(self, name: str, countries: List[str], rates: Dict[str, Decimal]):
        self.name = name
        self.countries = countries
        self.rates = rates  # {'standard': 10.00, 'express': 25.00}
    
    def get_rate(self, method: str = 'standard') -> Decimal:
        """Get shipping rate for method."""
        return self.rates.get(method, Decimal('0.00'))
    
    def applies_to_country(self, country_code: str) -> bool:
        """Check if zone applies to country."""
        return country_code.upper() in [c.upper() for c in self.countries]


class TaxRule:
    """Tax calculation rule."""
    
    def __init__(self, name: str, rate: Decimal, countries: List[str], product_types: List[str] = None):
        self.name = name
        self.rate = rate  # e.g., 0.20 for 20%
        self.countries = countries
        self.product_types = product_types or []
    
    def applies_to(self, country_code: str, product_type: str = None) -> bool:
        """Check if tax rule applies."""
        country_match = country_code.upper() in [c.upper() for c in self.countries]
        
        if not self.product_types:
            return country_match
        
        type_match = product_type in self.product_types if product_type else True
        return country_match and type_match
    
    def calculate_tax(self, amount: Decimal) -> Decimal:
        """Calculate tax amount."""
        return amount * self.rate


class DiscountCode:
    """Discount code with validation."""
    
    TYPE_PERCENTAGE = 'percentage'
    TYPE_FIXED = 'fixed'
    TYPE_FREE_SHIPPING = 'free_shipping'
    
    def __init__(
        self,
        code: str,
        discount_type: str,
        value: Decimal,
        min_purchase: Decimal = None,
        max_uses: int = None,
        expires_at = None,
        active: bool = True
    ):
        self.code = code.upper()
        self.discount_type = discount_type
        self.value = value
        self.min_purchase = min_purchase or Decimal('0.00')
        self.max_uses = max_uses
        self.expires_at = expires_at
        self.active = active
        self.use_count = 0
    
    def is_valid(self, cart_total: Decimal = None) -> tuple[bool, str]:
        """Validate discount code."""
        if not self.active:
            return False, "Discount code is inactive"
        
        if self.expires_at and timezone.now() > self.expires_at:
            return False, "Discount code has expired"
        
        if self.max_uses and self.use_count >= self.max_uses:
            return False, "Discount code has reached maximum uses"
        
        if cart_total and cart_total < self.min_purchase:
            return False, f"Minimum purchase of ${self.min_purchase} required"
        
        return True, "Valid"
    
    def calculate_discount(self, subtotal: Decimal, shipping: Decimal = None) -> Dict[str, Decimal]:
        """Calculate discount amounts."""
        discount_amount = Decimal('0.00')
        shipping_discount = Decimal('0.00')
        
        if self.discount_type == self.TYPE_PERCENTAGE:
            discount_amount = subtotal * (self.value / Decimal('100'))
        elif self.discount_type == self.TYPE_FIXED:
            discount_amount = min(self.value, subtotal)
        elif self.discount_type == self.TYPE_FREE_SHIPPING and shipping:
            shipping_discount = shipping
        
        return {
            'discount_amount': discount_amount,
            'shipping_discount': shipping_discount,
            'total_discount': discount_amount + shipping_discount,
        }


class InventoryAlert:
    """Inventory alert system."""
    
    ALERT_LOW_STOCK = 'low_stock'
    ALERT_OUT_OF_STOCK = 'out_of_stock'
    ALERT_RESTOCK = 'restock'
    
    @staticmethod
    def check_variant_inventory(variant, threshold: int = 5) -> Optional[str]:
        """Check variant inventory and return alert type if needed."""
        if not variant.track_inventory:
            return None
        
        if variant.inventory <= 0:
            return InventoryAlert.ALERT_OUT_OF_STOCK
        elif variant.inventory <= threshold:
            return InventoryAlert.ALERT_LOW_STOCK
        
        return None
    
    @staticmethod
    def get_low_stock_variants(site, threshold: int = 5):
        """Get all low stock variants for a site."""
        from .models import ProductVariant
        
        return ProductVariant.objects.filter(
            product__site=site,
            track_inventory=True,
            inventory__lte=threshold,
            inventory__gt=0,
            is_active=True
        ).select_related('product')
    
    @staticmethod
    def get_out_of_stock_variants(site):
        """Get all out of stock variants for a site."""
        from .models import ProductVariant
        
        return ProductVariant.objects.filter(
            product__site=site,
            track_inventory=True,
            inventory=0,
            is_active=True
        ).select_related('product')


class CommerceService:
    """
    Advanced commerce service.
    
    Features:
    - Shipping zone calculation
    - Tax calculation
    - Discount code validation and application
    - Inventory alerts
    """
    
    def __init__(self):
        self.shipping_zones = self._load_shipping_zones()
        self.tax_rules = self._load_tax_rules()
    
    def _load_shipping_zones(self) -> List[ShippingZone]:
        """Load shipping zones configuration."""
        return [
            ShippingZone(
                name='United States',
                countries=['US'],
                rates={
                    'standard': Decimal('5.99'),
                    'express': Decimal('15.99'),
                    'overnight': Decimal('29.99'),
                }
            ),
            ShippingZone(
                name='Canada',
                countries=['CA'],
                rates={
                    'standard': Decimal('9.99'),
                    'express': Decimal('24.99'),
                }
            ),
            ShippingZone(
                name='Europe',
                countries=['GB', 'FR', 'DE', 'IT', 'ES', 'NL', 'BE', 'AT', 'CH'],
                rates={
                    'standard': Decimal('12.99'),
                    'express': Decimal('29.99'),
                }
            ),
            ShippingZone(
                name='Rest of World',
                countries=['*'],  # Wildcard for all other countries
                rates={
                    'standard': Decimal('19.99'),
                }
            ),
        ]
    
    def _load_tax_rules(self) -> List[TaxRule]:
        """Load tax rules configuration."""
        return [
            TaxRule(
                name='US Sales Tax',
                rate=Decimal('0.08'),  # 8% average
                countries=['US']
            ),
            TaxRule(
                name='Canada GST/HST',
                rate=Decimal('0.13'),  # 13% HST
                countries=['CA']
            ),
            TaxRule(
                name='UK VAT',
                rate=Decimal('0.20'),  # 20% VAT
                countries=['GB']
            ),
            TaxRule(
                name='EU VAT',
                rate=Decimal('0.21'),  # 21% average
                countries=['FR', 'DE', 'IT', 'ES', 'NL', 'BE', 'AT']
            ),
        ]
    
    def calculate_shipping(
        self,
        country_code: str,
        method: str = 'standard',
        cart_total: Decimal = None,
        free_shipping_threshold: Decimal = None
    ) -> Dict[str, Any]:
        """
        Calculate shipping cost.
        
        Args:
            country_code: ISO country code
            method: Shipping method (standard, express, overnight)
            cart_total: Cart subtotal
            free_shipping_threshold: Free shipping threshold amount
        
        Returns:
            Shipping calculation result
        """
        # Check for free shipping
        if free_shipping_threshold and cart_total and cart_total >= free_shipping_threshold:
            return {
                'cost': Decimal('0.00'),
                'method': method,
                'zone': 'Free Shipping',
                'free_shipping': True,
            }
        
        # Find applicable zone
        for zone in self.shipping_zones:
            if zone.applies_to_country(country_code):
                cost = zone.get_rate(method)
                return {
                    'cost': cost,
                    'method': method,
                    'zone': zone.name,
                    'free_shipping': False,
                }
        
        # Fallback to rest of world
        rest_of_world = next((z for z in self.shipping_zones if '*' in z.countries), None)
        if rest_of_world:
            cost = rest_of_world.get_rate(method)
            return {
                'cost': cost,
                'method': method,
                'zone': rest_of_world.name,
                'free_shipping': False,
            }
        
        return {
            'cost': Decimal('0.00'),
            'method': method,
            'zone': 'Unknown',
            'free_shipping': False,
        }
    
    def calculate_tax(
        self,
        amount: Decimal,
        country_code: str,
        product_type: str = None
    ) -> Dict[str, Any]:
        """
        Calculate tax.
        
        Args:
            amount: Amount to calculate tax on
            country_code: ISO country code
            product_type: Optional product type for specific tax rules
        
        Returns:
            Tax calculation result
        """
        for rule in self.tax_rules:
            if rule.applies_to(country_code, product_type):
                tax_amount = rule.calculate_tax(amount)
                return {
                    'tax_amount': tax_amount,
                    'tax_rate': rule.rate,
                    'tax_name': rule.name,
                }
        
        return {
            'tax_amount': Decimal('0.00'),
            'tax_rate': Decimal('0.00'),
            'tax_name': 'No Tax',
        }
    
    def apply_discount(
        self,
        discount_code: DiscountCode,
        subtotal: Decimal,
        shipping: Decimal = None
    ) -> Dict[str, Any]:
        """Apply discount code to order."""
        is_valid, message = discount_code.is_valid(subtotal)
        
        if not is_valid:
            return {
                'valid': False,
                'message': message,
                'discount_amount': Decimal('0.00'),
                'shipping_discount': Decimal('0.00'),
                'total_discount': Decimal('0.00'),
            }
        
        discounts = discount_code.calculate_discount(subtotal, shipping)
        
        return {
            'valid': True,
            'message': 'Discount applied',
            'code': discount_code.code,
            'type': discount_code.discount_type,
            **discounts,
        }
    
    def calculate_order_total(
        self,
        subtotal: Decimal,
        country_code: str,
        shipping_method: str = 'standard',
        discount_code: Optional[DiscountCode] = None,
        free_shipping_threshold: Decimal = None
    ) -> Dict[str, Decimal]:
        """
        Calculate complete order total.
        
        Returns:
            Complete order calculation breakdown
        """
        # Calculate shipping
        shipping_result = self.calculate_shipping(
            country_code,
            shipping_method,
            subtotal,
            free_shipping_threshold
        )
        shipping_cost = shipping_result['cost']
        
        # Apply discount
        discount_amount = Decimal('0.00')
        shipping_discount = Decimal('0.00')
        
        if discount_code:
            discount_result = self.apply_discount(discount_code, subtotal, shipping_cost)
            if discount_result['valid']:
                discount_amount = discount_result['discount_amount']
                shipping_discount = discount_result['shipping_discount']
        
        # Calculate tax on discounted subtotal
        taxable_amount = subtotal - discount_amount
        tax_result = self.calculate_tax(taxable_amount, country_code)
        tax_amount = tax_result['tax_amount']
        
        # Calculate final total
        final_shipping = shipping_cost - shipping_discount
        total = taxable_amount + tax_amount + final_shipping
        
        return {
            'subtotal': subtotal,
            'discount': discount_amount,
            'shipping': shipping_cost,
            'shipping_discount': shipping_discount,
            'final_shipping': final_shipping,
            'tax': tax_amount,
            'tax_rate': tax_result['tax_rate'],
            'total': total,
        }


# Global commerce service instance
commerce_service = CommerceService()
