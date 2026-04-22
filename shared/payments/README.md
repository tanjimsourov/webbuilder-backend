# shared/payments/

Shared payment abstraction used by commerce checkout/order flows.

- Uses `provider.services.providers.payment` for gateway-specific behavior.
- Adds idempotency key generation via `shared/payments/service.py`.
