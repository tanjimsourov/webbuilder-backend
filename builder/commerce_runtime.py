from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .models import Cart, DiscountCode, ShippingRate, ShippingZone, TaxRate


def quantize_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _normalized_location_value(address: dict[str, Any] | None, *keys: str) -> str:
    payload = address or {}
    for key in keys:
        raw_value = payload.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip().upper()
        if value:
            return value
    return ""


def shipping_country_for(address: dict[str, Any] | None) -> str:
    return _normalized_location_value(address, "country", "country_code")


def shipping_state_for(address: dict[str, Any] | None) -> str:
    return _normalized_location_value(address, "state", "state_code", "province", "region")


def serialize_shipping_rate(rate: ShippingRate) -> dict[str, Any]:
    return {
        "id": rate.id,
        "zone": rate.zone_id,
        "name": rate.name,
        "method_code": rate.method_code,
        "price": str(quantize_money(rate.price)),
        "estimated_days_min": rate.estimated_days_min,
        "estimated_days_max": rate.estimated_days_max,
        "active": rate.active,
    }


def resolve_shipping_zone(site, country_code: str) -> ShippingZone | None:
    if not country_code:
        return None

    zones = (
        site.shipping_zones.filter(active=True)
        .prefetch_related("rates")
        .order_by("name", "id")
    )
    normalized = country_code.upper()

    for zone in zones:
        countries = [str(code).upper() for code in zone.countries]
        if normalized in countries:
            return zone

    for zone in zones:
        countries = [str(code).upper() for code in zone.countries]
        if "*" in countries:
            return zone

    return None


def list_available_shipping_rates(site, shipping_address: dict[str, Any] | None) -> tuple[ShippingZone | None, list[ShippingRate]]:
    zone = resolve_shipping_zone(site, shipping_country_for(shipping_address))
    if not zone:
        return None, []
    rates = list(zone.rates.filter(active=True).order_by("price", "estimated_days_min", "id"))
    return zone, rates


def resolve_tax_rate(site, shipping_address: dict[str, Any] | None) -> TaxRate | None:
    country_code = shipping_country_for(shipping_address)
    state_code = shipping_state_for(shipping_address)
    if not country_code:
        return None

    candidates = []
    for tax_rate in site.tax_rates.filter(active=True).order_by("name", "id"):
        if tax_rate.applies_to(country_code, state_code):
            candidates.append(tax_rate)

    if not candidates:
        return None

    candidates.sort(key=lambda item: (0 if item.states else 1, item.name.lower()))
    return candidates[0]


def resolve_discount_code(site, code: str | None) -> DiscountCode | None:
    if not code:
        return None
    normalized = code.strip().upper()
    if not normalized:
        return None
    return site.discount_codes.filter(code__iexact=normalized).first()


def calculate_cart_pricing(
    cart: Cart,
    *,
    shipping_address: dict[str, Any] | None = None,
    shipping_rate_id: int | None = None,
    discount_code: str | None = None,
) -> dict[str, Any]:
    subtotal = quantize_money(cart.subtotal or 0)
    zone, available_rates = list_available_shipping_rates(cart.site, shipping_address)
    selected_rate = None

    if available_rates:
        if shipping_rate_id:
            selected_rate = next((rate for rate in available_rates if rate.id == shipping_rate_id), None)
            if selected_rate is None:
                raise ValueError("Selected shipping rate is not available for this shipping address.")
        else:
            selected_rate = available_rates[0]

    shipping_total = quantize_money(selected_rate.price if selected_rate else 0)
    shipping_original_total = shipping_total

    discount = resolve_discount_code(cart.site, discount_code)
    discount_amount = Decimal("0.00")
    shipping_discount = Decimal("0.00")
    discount_summary = None
    if discount:
        is_valid, message = discount.is_valid(subtotal)
        if not is_valid:
            raise ValueError(message)

        if discount.discount_type == DiscountCode.TYPE_PERCENTAGE:
            discount_amount = quantize_money(subtotal * (discount.value / Decimal("100")))
        elif discount.discount_type == DiscountCode.TYPE_FIXED:
            discount_amount = quantize_money(min(discount.value, subtotal))
        elif discount.discount_type == DiscountCode.TYPE_FREE_SHIPPING and shipping_total > 0:
            shipping_discount = shipping_total

        discount_total = quantize_money(discount_amount + shipping_discount)
        discount_summary = {
            "id": discount.id,
            "code": discount.code,
            "discount_type": discount.discount_type,
            "value": str(quantize_money(discount.value)),
            "discount_amount": str(quantize_money(discount_amount)),
            "shipping_discount": str(quantize_money(shipping_discount)),
            "total_discount": str(discount_total),
        }
    else:
        discount_total = Decimal("0.00")

    shipping_total = quantize_money(max(shipping_total - shipping_discount, Decimal("0.00")))
    taxable_subtotal = quantize_money(max(subtotal - discount_amount, Decimal("0.00")))
    tax_rate = resolve_tax_rate(cart.site, shipping_address)
    tax_total = quantize_money((taxable_subtotal + shipping_total) * tax_rate.rate) if tax_rate else Decimal("0.00")
    total = quantize_money(max(taxable_subtotal + shipping_total + tax_total, Decimal("0.00")))

    return {
        "subtotal": str(subtotal),
        "shipping_total": str(shipping_total),
        "shipping_original_total": str(shipping_original_total),
        "tax_total": str(tax_total),
        "discount_total": str(quantize_money(discount_total)),
        "total": str(total),
        "shipping_zone": (
            {
                "id": zone.id,
                "name": zone.name,
                "countries": zone.countries,
            }
            if zone
            else None
        ),
        "available_shipping_rates": [serialize_shipping_rate(rate) for rate in available_rates],
        "shipping_rate": serialize_shipping_rate(selected_rate) if selected_rate else None,
        "discount": discount_summary,
        "tax_rate": (
            {
                "id": tax_rate.id,
                "name": tax_rate.name,
                "rate": str(tax_rate.rate),
                "countries": tax_rate.countries,
                "states": tax_rate.states,
            }
            if tax_rate
            else None
        ),
        "pricing_details": {
            "shipping_country": shipping_country_for(shipping_address),
            "shipping_state": shipping_state_for(shipping_address),
            "shipping_zone_id": zone.id if zone else None,
            "shipping_rate_id": selected_rate.id if selected_rate else None,
            "shipping_method_code": selected_rate.method_code if selected_rate else "",
            "shipping_method_name": selected_rate.name if selected_rate else "",
            "discount_code": discount.code if discount else "",
            "tax_rate_id": tax_rate.id if tax_rate else None,
        },
        "discount_code_obj": discount,
    }
