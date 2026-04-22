# commerce/

Production commerce domain for catalog, cart/checkout, orders, payments, inventory, and fulfillment.

## Domain coverage

- Catalog: `products`, `product_variants`, `product_categories`, `product_collections`, `product_media`.
- Checkout: `carts`, `cart_items`, `checkout_sessions`, `discount_codes`.
- Customers: `customers`, `customer_addresses`.
- Orders: `orders`, `order_items`, `shipments`, `tax_records`, `order_audit_logs`.
- Payments: `payments`, `refunds`, Stripe-backed payment intent + webhook processing.
- Inventory: `inventories` with reservation flow via `stock_reservations`.
- Events and risk: `commerce_events`, `fraud_signals`.

## APIs

- Admin CRUD and operations are exposed under `api/` routes in `commerce/urls.py`.
- Storefront/public APIs:
  - Catalog/product: `public/shop/<site_slug>/products/`, `public/shop/<site_slug>/products/<product_slug>/`
  - Cart/checkout: `public/shop/<site_slug>/cart/*`, `public/shop/<site_slug>/checkout/*`
  - Checkout sessions: `public/shop/<site_slug>/checkout/session/`, `public/shop/<site_slug>/checkout/complete/`
  - Shipping/tax quote: `public/shop/<site_slug>/shipping-rates/`
  - Event ingestion: `public/shop/<site_slug>/events/`

## Payment flow

1. Storefront creates order from checkout (`create_order_from_checkout`).
2. Client requests payment intent (`payments/intent/`) for the order.
3. Stripe intent metadata links back to order.
4. Webhook updates payment/order status idempotently (`payments/webhook/`).
5. Receipt email abstraction sends to customer (`commerce.services.send_receipt_email`).

## Order lifecycle

- `pending` -> `paid` -> `fulfilled`
- Cancellation path: `pending|paid` -> `cancelled`
- Fulfillment tracking is independent via `fulfillment_status`: `unfulfilled|partial|fulfilled|cancelled`.
- All critical transitions are written to `order_audit_logs`.

## Refund lifecycle

1. Admin triggers refund (order endpoint or refund API).
2. Gateway refund is requested through shared payment abstraction.
3. `refunds` row is created and order totals/status are updated.
4. Full refunds set `payment_status=refunded` and cancel order state.
5. Refund events are emitted to analytics/webhook stream.

## Inventory behavior

- Inventory source of truth is `Inventory.on_hand`.
- Reserved inventory is tracked in `Inventory.reserved`.
- Available stock is computed as `on_hand - reserved`.
- Checkout session creation reserves stock in `stock_reservations`.
- Order completion commits reservations and decrements `on_hand`.
- Expired/cancelled checkout sessions release reservations.
