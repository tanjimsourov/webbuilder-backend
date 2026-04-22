from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from provider.services import providers


@dataclass(frozen=True)
class PaymentIntentResult:
    provider: str
    intent_id: str
    client_secret: str
    amount: int
    currency: str
    idempotency_key: str


class PaymentGatewayFacade:
    """Shared payment abstraction used by commerce/public checkout flows."""

    def create_idempotency_key(self, *, order_id: int, request_id: str = "") -> str:
        payload = f"commerce-order:{order_id}:{request_id}"
        return sha256(payload.encode("utf-8")).hexdigest()[:48]

    def create_intent(self, order, *, request_id: str = "") -> PaymentIntentResult:
        idempotency_key = self.create_idempotency_key(order_id=order.id, request_id=request_id)
        result = providers.payment.create_intent(order, idempotency_key=idempotency_key)
        return PaymentIntentResult(
            provider=result.get("provider", ""),
            intent_id=result.get("intent_id", ""),
            client_secret=result.get("client_secret", ""),
            amount=int(result.get("amount", 0)),
            currency=result.get("currency", ""),
            idempotency_key=result.get("idempotency_key", idempotency_key),
        )

    def refund(self, order, *, amount: Decimal | None = None) -> dict:
        return providers.payment.refund(order, amount=amount)

    def process_webhook(self, *, payload: bytes, signature: str) -> dict:
        return providers.payment.process_webhook(payload=payload, signature=signature)


payment_gateway = PaymentGatewayFacade()
