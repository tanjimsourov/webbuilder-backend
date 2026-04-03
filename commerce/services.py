"""Commerce domain service wrappers."""

from __future__ import annotations

from typing import Any

from builder import services as builder_services

build_order_number = builder_services.build_order_number
ensure_site_commerce_modules = builder_services.ensure_site_commerce_modules
ensure_variant_inventory = builder_services.ensure_variant_inventory
preview_url_for_product = builder_services.preview_url_for_product
quantize_money = builder_services.quantize_money
resolve_variant = builder_services.resolve_variant
sync_cart_item = builder_services.sync_cart_item


def get_cart_for_session(site: Any, session: Any):
    """Return an open cart for the session, creating one when needed."""
    return builder_services.get_or_create_cart(site, session)


def recalculate_cart_totals(cart: Any):
    """Recalculate cart totals after item changes."""
    return builder_services.recalculate_cart(cart)


def create_order(cart: Any, customer: dict[str, Any], metadata: dict[str, Any] | None = None):
    """Create an order from a cart."""
    return builder_services.create_order_from_cart(cart, customer, metadata=metadata)


__all__ = [
    "build_order_number",
    "create_order",
    "ensure_site_commerce_modules",
    "ensure_variant_inventory",
    "get_cart_for_session",
    "preview_url_for_product",
    "quantize_money",
    "recalculate_cart_totals",
    "resolve_variant",
    "sync_cart_item",
]
