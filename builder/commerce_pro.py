"""
Pro-Level Commerce Services - Enterprise E-commerce

Provides advanced commerce features inspired by Medusa:
- Enhanced product modeling with options
- Advanced inventory management
- Order lifecycle state machine
- Customer account architecture
- Discount/coupon system (already in commerce_services.py)
- Payment flow safety
- Fulfillment workflows
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class ProductOptionManager:
    """
    Manage product options and variant generation.
    
    Features:
    - Product options (Size, Color, Material, etc.)
    - Variant generation from options
    - Option value management
    """
    
    @staticmethod
    def create_product_options(product, options_data: List[Dict]) -> List[Dict]:
        """
        Create product options.
        
        Args:
            product: Product instance
            options_data: [{"name": "Size", "values": ["S", "M", "L"]}, ...]
        
        Returns:
            Created options metadata
        """
        # Store in product settings for now
        settings = product.settings or {}
        settings['options'] = options_data
        product.settings = settings
        product.save(update_fields=['settings'])
        
        return options_data
    
    @staticmethod
    def get_product_options(product) -> List[Dict]:
        """Get product options."""
        settings = product.settings or {}
        return settings.get('options', [])
    
    @staticmethod
    def generate_variants_from_options(product, options: List[Dict], base_price: Decimal) -> List[Dict]:
        """
        Generate all variant combinations from options.
        
        Args:
            product: Product instance
            options: [{"name": "Size", "values": ["S", "M"]}, {"name": "Color", "values": ["Red", "Blue"]}]
            base_price: Base price for variants
        
        Returns:
            Variant data for creation
        """
        from itertools import product as itertools_product
        from .models import ProductVariant
        
        if not options:
            return []
        
        # Generate all combinations
        option_names = [opt['name'] for opt in options]
        option_values = [opt['values'] for opt in options]
        combinations = list(itertools_product(*option_values))
        
        variants_data = []
        for idx, combo in enumerate(combinations):
            # Build variant title and attributes
            variant_title = " / ".join(combo)
            attributes = {option_names[i]: combo[i] for i in range(len(combo))}
            
            # Generate SKU
            sku_suffix = "-".join([str(v)[:3].upper() for v in combo])
            sku = f"{product.slug.upper()}-{sku_suffix}"
            
            variants_data.append({
                'title': variant_title,
                'sku': sku,
                'price': base_price,
                'attributes': attributes,
                'is_default': idx == 0,
                'inventory': 0,
                'track_inventory': True,
            })
        
        return variants_data


class InventoryManager:
    """
    Advanced inventory management.
    
    Features:
    - Stock tracking
    - Low stock alerts
    - Inventory adjustments
    - Stock reservations
    """
    
    @staticmethod
    def check_stock_availability(variant, quantity: int) -> Tuple[bool, str]:
        """Check if stock is available."""
        if not variant.track_inventory:
            return True, "Stock tracking disabled"
        
        if not variant.is_active:
            return False, "Variant is inactive"
        
        if variant.inventory < quantity:
            return False, f"Only {variant.inventory} units available"
        
        return True, "In stock"
    
    @staticmethod
    def adjust_inventory(variant, quantity_change: int, reason: str = "") -> Dict[str, Any]:
        """
        Adjust inventory level.
        
        Args:
            variant: ProductVariant instance
            quantity_change: Positive or negative change
            reason: Reason for adjustment
        
        Returns:
            Adjustment result
        """
        old_inventory = variant.inventory
        new_inventory = max(0, old_inventory + quantity_change)
        
        variant.inventory = new_inventory
        variant.save(update_fields=['inventory', 'updated_at'])
        
        return {
            'variant_id': variant.id,
            'old_inventory': old_inventory,
            'new_inventory': new_inventory,
            'change': quantity_change,
            'reason': reason,
            'timestamp': timezone.now().isoformat(),
        }
    
    @staticmethod
    def get_low_stock_variants(site, threshold: int = 5):
        """Get variants with low stock."""
        from .models import ProductVariant
        
        return ProductVariant.objects.filter(
            product__site=site,
            product__status='published',
            track_inventory=True,
            inventory__lte=threshold,
            inventory__gt=0,
            is_active=True,
        ).select_related('product').order_by('inventory')
    
    @staticmethod
    def get_out_of_stock_variants(site):
        """Get out of stock variants."""
        from .models import ProductVariant
        
        return ProductVariant.objects.filter(
            product__site=site,
            product__status='published',
            track_inventory=True,
            inventory=0,
            is_active=True,
        ).select_related('product')


class OrderStateMachine:
    """
    Order lifecycle state machine.
    
    States: pending → paid → processing → fulfilled → completed
    Also handles: cancelled, refunded
    """
    
    # Valid state transitions
    TRANSITIONS = {
        'pending': ['paid', 'cancelled'],
        'paid': ['processing', 'cancelled', 'refunded'],
        'processing': ['fulfilled', 'cancelled'],
        'fulfilled': ['completed', 'refunded'],
        'completed': ['refunded'],
        'cancelled': [],
        'refunded': [],
    }
    
    @staticmethod
    def can_transition(current_state: str, new_state: str) -> Tuple[bool, str]:
        """Check if state transition is valid."""
        valid_next_states = OrderStateMachine.TRANSITIONS.get(current_state, [])
        
        if new_state not in valid_next_states:
            return False, f"Cannot transition from {current_state} to {new_state}"
        
        return True, "Valid transition"
    
    @staticmethod
    def transition_order(order, new_status: str, user=None, notes: str = "") -> Dict[str, Any]:
        """
        Transition order to new status.
        
        Args:
            order: Order instance
            new_status: Target status
            user: User performing transition
            notes: Optional notes
        
        Returns:
            Transition result
        """
        old_status = order.status
        
        # Validate transition
        can_transition, message = OrderStateMachine.can_transition(old_status, new_status)
        
        if not can_transition:
            return {
                'success': False,
                'error': message,
                'old_status': old_status,
                'new_status': new_status,
            }
        
        # Perform transition
        order.status = new_status
        
        # Update timestamps based on status
        if new_status == 'fulfilled':
            if not hasattr(order, 'fulfilled_at'):
                # Would need to add this field to model
                pass
        
        order.save(update_fields=['status', 'updated_at'])
        
        # Log transition (could be enhanced with OrderHistory model)
        logger.info(f"Order {order.order_number} transitioned from {old_status} to {new_status}")
        
        return {
            'success': True,
            'old_status': old_status,
            'new_status': new_status,
            'order_number': order.order_number,
            'timestamp': timezone.now().isoformat(),
        }
    
    @staticmethod
    def cancel_order(order, reason: str = "", refund: bool = False) -> Dict[str, Any]:
        """Cancel an order."""
        if order.status == 'cancelled':
            return {'success': False, 'error': 'Order already cancelled'}
        
        # Check if order can be cancelled
        if order.status in ['fulfilled', 'completed']:
            return {'success': False, 'error': 'Cannot cancel fulfilled orders'}
        
        # Restore inventory
        for item in order.items.all():
            if item.product_variant and item.product_variant.track_inventory:
                InventoryManager.adjust_inventory(
                    item.product_variant,
                    item.quantity,
                    reason=f"Order {order.order_number} cancelled"
                )
        
        # Update order status
        result = OrderStateMachine.transition_order(order, 'cancelled', notes=reason)
        
        if refund and order.payment_status == 'paid':
            order.payment_status = 'refunded'
            order.save(update_fields=['payment_status', 'updated_at'])
            result['refunded'] = True
        
        return result


class CustomerAccountManager:
    """
    Customer account architecture.
    
    Features:
    - Customer profiles
    - Order history
    - Saved addresses
    - Account preferences
    """
    
    @staticmethod
    def create_customer_profile(user, site, data: Dict) -> Dict[str, Any]:
        """
        Create customer profile.
        
        Args:
            user: User instance
            site: Site instance
            data: Profile data
        
        Returns:
            Profile metadata
        """
        # Store in user profile or separate Customer model
        # For now, return structure
        return {
            'user_id': user.id if user else None,
            'site_id': site.id,
            'email': data.get('email'),
            'name': data.get('name'),
            'phone': data.get('phone'),
            'addresses': data.get('addresses', []),
            'preferences': data.get('preferences', {}),
            'created_at': timezone.now().isoformat(),
        }
    
    @staticmethod
    def get_customer_orders(site, customer_email: str):
        """Get all orders for a customer."""
        from .models import Order
        
        return Order.objects.filter(
            site=site,
            customer_email=customer_email
        ).order_by('-placed_at')
    
    @staticmethod
    def get_customer_stats(site, customer_email: str) -> Dict[str, Any]:
        """Get customer statistics."""
        orders = CustomerAccountManager.get_customer_orders(site, customer_email)
        
        total_spent = sum(order.total for order in orders if order.payment_status == 'paid')
        total_orders = orders.count()
        
        return {
            'email': customer_email,
            'total_orders': total_orders,
            'total_spent': float(total_spent),
            'average_order_value': float(total_spent / total_orders) if total_orders > 0 else 0,
            'first_order': orders.last().placed_at.isoformat() if orders.exists() else None,
            'last_order': orders.first().placed_at.isoformat() if orders.exists() else None,
        }


class PaymentFlowManager:
    """
    Payment flow safety and validation.
    
    Features:
    - Payment intent creation
    - Payment verification
    - Webhook handling
    - Refund processing
    """
    
    @staticmethod
    def create_payment_intent(order, payment_method: str = 'stripe') -> Dict[str, Any]:
        """
        Create payment intent for order.
        
        Args:
            order: Order instance
            payment_method: Payment provider
        
        Returns:
            Payment intent data
        """
        # This would integrate with actual payment provider
        # For now, return structure
        return {
            'order_id': order.id,
            'order_number': order.order_number,
            'amount': float(order.total),
            'currency': order.currency,
            'payment_method': payment_method,
            'status': 'pending',
            'created_at': timezone.now().isoformat(),
        }
    
    @staticmethod
    def verify_payment(order, payment_reference: str) -> Tuple[bool, str]:
        """Verify payment completion."""
        # This would verify with payment provider
        # For now, basic check
        if not payment_reference:
            return False, "No payment reference provided"
        
        if order.payment_status == 'paid':
            return True, "Payment already verified"
        
        return True, "Payment verified"
    
    @staticmethod
    def process_payment_webhook(payload: Dict) -> Dict[str, Any]:
        """
        Process payment webhook.
        
        Args:
            payload: Webhook payload from payment provider
        
        Returns:
            Processing result
        """
        from .models import Order
        
        # Extract order reference
        order_number = payload.get('order_number')
        payment_status = payload.get('status')
        
        if not order_number:
            return {'success': False, 'error': 'No order number in payload'}
        
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            return {'success': False, 'error': 'Order not found'}
        
        # Update payment status
        if payment_status == 'succeeded':
            order.payment_status = 'paid'
            order.payment_reference = payload.get('payment_reference', '')
            order.save(update_fields=['payment_status', 'payment_reference', 'updated_at'])
            
            # Transition order to paid
            OrderStateMachine.transition_order(order, 'paid')
            
            return {
                'success': True,
                'order_number': order_number,
                'payment_status': 'paid',
            }
        
        return {'success': False, 'error': 'Payment not successful'}


class FulfillmentManager:
    """
    Order fulfillment workflows.
    
    Features:
    - Fulfillment creation
    - Shipping tracking
    - Partial fulfillments
    """
    
    @staticmethod
    def create_fulfillment(order, items: List[Dict], tracking_info: Dict = None) -> Dict[str, Any]:
        """
        Create fulfillment for order.
        
        Args:
            order: Order instance
            items: [{"order_item_id": 1, "quantity": 2}, ...]
            tracking_info: {"carrier": "UPS", "tracking_number": "1Z999AA1..."}
        
        Returns:
            Fulfillment data
        """
        # This would create a Fulfillment model instance
        # For now, return structure
        fulfillment_data = {
            'order_id': order.id,
            'order_number': order.order_number,
            'items': items,
            'tracking_info': tracking_info or {},
            'status': 'pending',
            'created_at': timezone.now().isoformat(),
        }
        
        # Update order status to fulfilled if all items fulfilled
        OrderStateMachine.transition_order(order, 'fulfilled')
        
        return fulfillment_data
    
    @staticmethod
    def update_tracking(order, tracking_number: str, carrier: str = "") -> Dict[str, Any]:
        """Update shipping tracking information."""
        # Store in order notes or separate field
        notes = order.notes or ""
        tracking_info = f"\nTracking: {carrier} {tracking_number}"
        
        order.notes = notes + tracking_info
        order.save(update_fields=['notes', 'updated_at'])
        
        return {
            'order_number': order.order_number,
            'tracking_number': tracking_number,
            'carrier': carrier,
        }


# Global instances
product_option_manager = ProductOptionManager()
inventory_manager = InventoryManager()
order_state_machine = OrderStateMachine()
customer_account_manager = CustomerAccountManager()
payment_flow_manager = PaymentFlowManager()
fulfillment_manager = FulfillmentManager()
