from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.mail import send_mail

from builder.domain_services import build_verification_instructions, verify_domain_ownership
from builder.payment_services import PaymentProvider as PaymentProviderType
from builder.payment_services import get_payment_service
from shared.search.service import search_index


class StorageProvider(ABC):
    @abstractmethod
    def save_file(self, path: str, content) -> str:
        raise NotImplementedError


class ImageTransformProvider(ABC):
    @abstractmethod
    def build_url(self, source_url: str, **options: Any) -> str:
        raise NotImplementedError


class EmailProvider(ABC):
    @abstractmethod
    def send(self, *, subject: str, body: str, to: list[str], html: str = "") -> int:
        raise NotImplementedError


class SearchProvider(ABC):
    @abstractmethod
    def index(self, index_name: str, document: dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, index_name: str, document_id: str) -> bool:
        raise NotImplementedError


class DNSProvider(ABC):
    @abstractmethod
    def verify(self, domain_name: str, token: str) -> tuple[bool, str]:
        raise NotImplementedError

    @abstractmethod
    def verification_instructions(self, domain_name: str, token: str) -> dict[str, Any]:
        raise NotImplementedError


class PaymentProvider(ABC):
    @abstractmethod
    def create_intent(self, order, *, idempotency_key: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def refund(self, order, *, amount: Decimal | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def process_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        raise NotImplementedError


class ShippingProvider(ABC):
    @abstractmethod
    def list_rates(self, site, *, shipping_address: dict[str, Any] | None) -> list[dict[str, Any]]:
        raise NotImplementedError


class TaxProvider(ABC):
    @abstractmethod
    def calculate_tax(
        self,
        site,
        *,
        shipping_address: dict[str, Any] | None,
        taxable_subtotal: Decimal,
        shipping_total: Decimal,
    ) -> dict[str, Any]:
        raise NotImplementedError


class AIGenerationProvider(ABC):
    @abstractmethod
    def submit_job(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        workspace=None,
        site=None,
        requested_by=None,
        provider: str = "",
        model_name: str = "",
        queue: bool = True,
        metadata: dict[str, Any] | None = None,
    ):
        raise NotImplementedError

    @abstractmethod
    def process_job(self, ai_job):
        raise NotImplementedError


class DjangoStorageProvider(StorageProvider):
    def save_file(self, path: str, content) -> str:
        saved_path = default_storage.save(path, content)
        return default_storage.url(saved_path)


class QueryStringImageTransformProvider(ImageTransformProvider):
    def build_url(self, source_url: str, **options: Any) -> str:
        normalized = source_url or ""
        params = {str(key): value for key, value in options.items() if value not in (None, "", False)}
        if not params:
            return normalized
        separator = "&" if "?" in normalized else "?"
        return f"{normalized}{separator}{urlencode(params)}"


class DjangoEmailProvider(EmailProvider):
    def send(self, *, subject: str, body: str, to: list[str], html: str = "") -> int:
        return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, to, html_message=html or None, fail_silently=False)


class SharedSearchProvider(SearchProvider):
    def index(self, index_name: str, document: dict[str, Any]) -> bool:
        return bool(search_index.index_document(index_name, document))

    def delete(self, index_name: str, document_id: str) -> bool:
        return bool(search_index.delete_document(index_name, document_id))


class DomainServiceDNSProvider(DNSProvider):
    def verify(self, domain_name: str, token: str) -> tuple[bool, str]:
        return verify_domain_ownership(domain_name, token)

    def verification_instructions(self, domain_name: str, token: str) -> dict[str, Any]:
        return build_verification_instructions(domain_name, token)


class StripePaymentProvider(PaymentProvider):
    def create_intent(self, order, *, idempotency_key: str | None = None) -> dict[str, Any]:
        service = get_payment_service()
        intent = service.create_checkout_session(order, provider=PaymentProviderType.STRIPE)
        return {
            "provider": intent.provider.value,
            "intent_id": intent.intent_id,
            "client_secret": intent.client_secret,
            "amount": intent.amount,
            "currency": intent.currency,
            "idempotency_key": idempotency_key or "",
        }

    def refund(self, order, *, amount: Decimal | None = None) -> dict[str, Any]:
        service = get_payment_service()
        result = service.refund_order(order, amount=amount)
        return {
            "success": bool(result.success),
            "refund_id": result.refund_id,
            "amount": result.amount,
            "status": result.status,
            "error": result.error_message,
        }

    def process_webhook(self, *, payload: bytes, signature: str) -> dict[str, Any]:
        service = get_payment_service()
        return service.process_webhook_event(PaymentProviderType.STRIPE, payload, signature)


class InternalShippingProvider(ShippingProvider):
    def list_rates(self, site, *, shipping_address: dict[str, Any] | None) -> list[dict[str, Any]]:
        from builder.commerce_runtime import list_available_shipping_rates, serialize_shipping_rate

        _, rates = list_available_shipping_rates(site, shipping_address)
        return [serialize_shipping_rate(rate) for rate in rates]


class InternalTaxProvider(TaxProvider):
    def calculate_tax(
        self,
        site,
        *,
        shipping_address: dict[str, Any] | None,
        taxable_subtotal: Decimal,
        shipping_total: Decimal,
    ) -> dict[str, Any]:
        from builder.commerce_runtime import quantize_money, resolve_tax_rate

        tax_rate = resolve_tax_rate(site, shipping_address)
        taxable_base = quantize_money(taxable_subtotal + shipping_total)
        tax_total = quantize_money(taxable_base * tax_rate.rate) if tax_rate else Decimal("0.00")
        return {
            "tax_total": tax_total,
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
        }


class SharedAIGenerationProvider(AIGenerationProvider):
    def submit_job(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        workspace=None,
        site=None,
        requested_by=None,
        provider: str = "",
        model_name: str = "",
        queue: bool = True,
        metadata: dict[str, Any] | None = None,
    ):
        from shared.ai.service import submit_ai_job

        return submit_ai_job(
            feature=feature,
            prompt=prompt,
            input_payload=input_payload,
            workspace=workspace,
            site=site,
            requested_by=requested_by,
            provider=provider,
            model_name=model_name,
            queue=queue,
            metadata=metadata,
        )

    def process_job(self, ai_job):
        from shared.ai.service import process_ai_job

        return process_ai_job(ai_job)


@dataclass(frozen=True)
class ProviderRegistry:
    storage: StorageProvider
    image: ImageTransformProvider
    email: EmailProvider
    search: SearchProvider
    dns: DNSProvider
    payment: PaymentProvider
    shipping: ShippingProvider
    tax: TaxProvider
    ai: AIGenerationProvider


def load_providers() -> ProviderRegistry:
    return ProviderRegistry(
        storage=DjangoStorageProvider(),
        image=QueryStringImageTransformProvider(),
        email=DjangoEmailProvider(),
        search=SharedSearchProvider(),
        dns=DomainServiceDNSProvider(),
        payment=StripePaymentProvider(),
        shipping=InternalShippingProvider(),
        tax=InternalTaxProvider(),
        ai=SharedAIGenerationProvider(),
    )


providers = load_providers()
