from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
import logging
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from notifications.services import trigger_webhooks
from provider.models import AIJob, AIModerationLog, AIUsageRecord, default_quota_for_scope
from shared.ai.safety import ModerationResult, moderate_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIProviderResponse:
    text: str
    payload: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model_name: str
    provider: str
    estimated_cost_usd: Decimal = Decimal("0")


class BaseAIProvider:
    name = "base"

    def is_available(self) -> bool:
        return True

    def default_model(self) -> str:
        return "mock-default"

    def generate(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        model_name: str = "",
    ) -> AIProviderResponse:
        raise NotImplementedError


class MockAIProvider(BaseAIProvider):
    name = "mock"

    def default_model(self) -> str:
        return "mock-v1"

    def _template(self, feature: str, prompt: str) -> str:
        normalized = feature.strip().lower()
        if normalized == AIJob.FEATURE_PAGE_OUTLINE:
            return f"1) Hero\n2) Features\n3) Testimonials\n4) FAQ\n5) CTA\n\nPrompt context: {prompt[:300]}"
        if normalized == AIJob.FEATURE_BLOG_DRAFT:
            return f"# Draft\n\n## Intro\n{prompt[:240]}\n\n## Key Points\n- Point 1\n- Point 2\n- Point 3\n"
        if normalized == AIJob.FEATURE_PRODUCT_DESCRIPTION:
            return f"Product description draft:\n\n{prompt[:500]}\n\n- Benefits\n- Use cases\n- Differentiators"
        if normalized == AIJob.FEATURE_SEO_META:
            return '{"meta_title":"High-converting title","meta_description":"Clear value proposition with CTA."}'
        if normalized == AIJob.FEATURE_IMAGE_ALT_TEXT:
            return "Descriptive alt text draft generated from provided context."
        if normalized == AIJob.FEATURE_FAQ_SCHEMA:
            return '{"faq":[{"q":"What is this?","a":"Answer."}],"schema":{"@type":"FAQPage"}}'
        if normalized == AIJob.FEATURE_SECTION_COMPOSITION:
            return '{"sections":["hero","benefits","pricing","faq","cta"]}'
        return f"AI output for feature '{feature}': {prompt[:500]}"

    def generate(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        model_name: str = "",
    ) -> AIProviderResponse:
        text = self._template(feature, prompt)
        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(text) // 4)
        total_tokens = prompt_tokens + completion_tokens
        return AIProviderResponse(
            text=text,
            payload={"input": input_payload or {}, "mock": True},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=model_name or self.default_model(),
            provider=self.name,
            estimated_cost_usd=Decimal("0"),
        )


class OpenAIProvider(BaseAIProvider):
    name = "openai"

    def is_available(self) -> bool:
        return bool(getattr(settings, "OPENAI_API_KEY", ""))

    def default_model(self) -> str:
        return getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

    def generate(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        model_name: str = "",
    ) -> AIProviderResponse:
        from openai import OpenAI

        client = OpenAI(api_key=getattr(settings, "OPENAI_API_KEY", ""))
        model = model_name or self.default_model()
        system = (
            "You are an assistant for a website builder backend. "
            "Return practical, concise content suitable for admin use."
        )
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=900,
        )
        text = ""
        try:
            text = (response.choices[0].message.content or "").strip()
        except Exception:
            text = ""
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
        return AIProviderResponse(
            text=text,
            payload={"input": input_payload or {}, "id": getattr(response, "id", "")},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=model,
            provider=self.name,
        )


class AnthropicProvider(BaseAIProvider):
    name = "anthropic"

    def is_available(self) -> bool:
        return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))

    def default_model(self) -> str:
        return getattr(settings, "ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    def generate(
        self,
        *,
        feature: str,
        prompt: str,
        input_payload: dict[str, Any] | None = None,
        model_name: str = "",
    ) -> AIProviderResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=getattr(settings, "ANTHROPIC_API_KEY", ""))
        model = model_name or self.default_model()
        response = client.messages.create(
            model=model,
            max_tokens=900,
            temperature=0.4,
            system="You create production-ready admin content for a website-builder platform.",
            messages=[{"role": "user", "content": prompt}],
        )
        content_parts = getattr(response, "content", []) or []
        text = ""
        for part in content_parts:
            if getattr(part, "type", "") == "text":
                text += getattr(part, "text", "")
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = prompt_tokens + completion_tokens
        return AIProviderResponse(
            text=text.strip(),
            payload={"input": input_payload or {}, "id": getattr(response, "id", "")},
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model_name=model,
            provider=self.name,
        )


def _available_providers() -> dict[str, BaseAIProvider]:
    return {
        "mock": MockAIProvider(),
        "openai": OpenAIProvider(),
        "anthropic": AnthropicProvider(),
    }


def _resolve_provider(name: str = "") -> BaseAIProvider:
    providers = _available_providers()
    preferred = (name or getattr(settings, "AI_DEFAULT_PROVIDER", "") or "").strip().lower()
    if preferred and preferred in providers and providers[preferred].is_available():
        return providers[preferred]
    for candidate in ("openai", "anthropic", "mock"):
        provider = providers[candidate]
        if provider.is_available():
            return provider
    return providers["mock"]


def _quota_window_start(period: str) -> timezone.datetime:
    now = timezone.now()
    if period == "daily":
        return now - timedelta(days=1)
    return now - timedelta(days=30)


def _quota_exceeded(*, ai_job: AIJob) -> tuple[bool, str]:
    quota = default_quota_for_scope(workspace=ai_job.workspace, site=ai_job.site, feature=ai_job.feature)
    if not quota.is_active:
        return False, ""
    since = max(quota.reset_at, _quota_window_start(quota.period))
    records = AIUsageRecord.objects.filter(
        workspace=ai_job.workspace,
        site=ai_job.site,
        feature=ai_job.feature,
        created_at__gte=since,
    )
    request_count = int(records.aggregate(total=Sum("request_count")).get("total") or 0)
    token_count = int(records.aggregate(total=Sum("total_tokens")).get("total") or 0)
    cost_total = records.aggregate(total=Sum("cost_usd")).get("total") or Decimal("0")

    if request_count >= quota.max_requests:
        return True, "quota.max_requests_exceeded"
    if token_count >= quota.max_tokens:
        return True, "quota.max_tokens_exceeded"
    if quota.max_cost_usd > 0 and cost_total >= quota.max_cost_usd:
        return True, "quota.max_cost_exceeded"
    return False, ""


def _create_moderation_log(ai_job: AIJob, *, stage: str, result: ModerationResult) -> None:
    AIModerationLog.objects.create(
        job=ai_job,
        stage=stage,
        blocked=result.blocked,
        reasons=result.reasons,
        raw_excerpt=result.sanitized_text[:1000],
    )


def _record_usage(ai_job: AIJob) -> AIUsageRecord:
    return AIUsageRecord.objects.create(
        workspace=ai_job.workspace,
        site=ai_job.site,
        job=ai_job,
        actor=ai_job.requested_by,
        feature=ai_job.feature,
        provider=ai_job.provider,
        model_name=ai_job.model_name,
        request_count=1,
        prompt_tokens=ai_job.prompt_tokens,
        completion_tokens=ai_job.completion_tokens,
        total_tokens=ai_job.total_tokens,
        cost_usd=ai_job.estimated_cost_usd,
        status=ai_job.status,
        metadata={"queue_job_id": ai_job.queue_job_id},
    )


def _emit_ai_webhook(ai_job: AIJob) -> None:
    if not ai_job.site_id:
        return
    event_name = "ai.job.completed" if ai_job.status == AIJob.STATUS_COMPLETED else "ai.job.failed"
    trigger_webhooks(
        ai_job.site,
        event_name,
        {
            "ai_job_id": ai_job.id,
            "feature": ai_job.feature,
            "status": ai_job.status,
            "provider": ai_job.provider,
            "model_name": ai_job.model_name,
            "error": ai_job.error_message,
        },
    )


def process_ai_job(ai_job: AIJob) -> AIJob:
    ai_job.status = AIJob.STATUS_RUNNING
    ai_job.started_at = timezone.now()
    ai_job.save(update_fields=["status", "started_at", "updated_at"])

    prompt_check = moderate_text(ai_job.prompt, max_length=12_000)
    _create_moderation_log(ai_job, stage=AIModerationLog.STAGE_PROMPT, result=prompt_check)
    ai_job.sanitized_prompt = prompt_check.sanitized_text
    ai_job.moderation_flags = prompt_check.reasons
    if prompt_check.blocked:
        ai_job.status = AIJob.STATUS_FAILED
        ai_job.error_message = "Prompt failed moderation checks."
        ai_job.completed_at = timezone.now()
        ai_job.save(
            update_fields=[
                "status",
                "error_message",
                "moderation_flags",
                "sanitized_prompt",
                "completed_at",
                "updated_at",
            ]
        )
        _record_usage(ai_job)
        _emit_ai_webhook(ai_job)
        return ai_job

    exceeded, reason = _quota_exceeded(ai_job=ai_job)
    if exceeded:
        ai_job.status = AIJob.STATUS_FAILED
        ai_job.error_message = reason
        ai_job.completed_at = timezone.now()
        ai_job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        _record_usage(ai_job)
        _emit_ai_webhook(ai_job)
        return ai_job

    provider = _resolve_provider(ai_job.provider)
    try:
        response = provider.generate(
            feature=ai_job.feature,
            prompt=prompt_check.sanitized_text,
            input_payload=ai_job.input_payload or {},
            model_name=ai_job.model_name,
        )
    except Exception as exc:
        logger.exception("AI provider failed for job %s", ai_job.id)
        ai_job.status = AIJob.STATUS_FAILED
        ai_job.error_message = str(exc)[:4000]
        ai_job.completed_at = timezone.now()
        ai_job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
        _record_usage(ai_job)
        _emit_ai_webhook(ai_job)
        return ai_job

    output_check = moderate_text(response.text, max_length=40_000)
    _create_moderation_log(ai_job, stage=AIModerationLog.STAGE_OUTPUT, result=output_check)
    if output_check.blocked:
        ai_job.status = AIJob.STATUS_FAILED
        ai_job.error_message = "Output failed moderation checks."
        ai_job.moderation_flags = [*ai_job.moderation_flags, *output_check.reasons]
        ai_job.completed_at = timezone.now()
        ai_job.save(update_fields=["status", "error_message", "moderation_flags", "completed_at", "updated_at"])
        _record_usage(ai_job)
        _emit_ai_webhook(ai_job)
        return ai_job

    ai_job.status = AIJob.STATUS_COMPLETED
    ai_job.provider = response.provider
    ai_job.model_name = response.model_name
    ai_job.output_payload = {
        "text": output_check.sanitized_text,
        "provider_payload": response.payload,
    }
    ai_job.prompt_tokens = response.prompt_tokens
    ai_job.completion_tokens = response.completion_tokens
    ai_job.total_tokens = response.total_tokens
    ai_job.estimated_cost_usd = response.estimated_cost_usd
    ai_job.completed_at = timezone.now()
    ai_job.save(
        update_fields=[
            "status",
            "provider",
            "model_name",
            "output_payload",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "completed_at",
            "updated_at",
        ]
    )
    _record_usage(ai_job)
    _emit_ai_webhook(ai_job)
    return ai_job


def submit_ai_job(
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
) -> AIJob:
    workspace_obj = workspace or (site.workspace if site and site.workspace_id else None)
    provider_name = (provider or getattr(settings, "AI_DEFAULT_PROVIDER", "") or "mock").strip().lower()
    ai_job = AIJob.objects.create(
        workspace=workspace_obj,
        site=site,
        requested_by=requested_by if getattr(requested_by, "is_authenticated", False) else None,
        feature=feature,
        provider=provider_name,
        model_name=model_name,
        status=AIJob.STATUS_QUEUED,
        prompt=prompt,
        input_payload=input_payload or {},
        metadata=metadata or {},
    )
    if queue:
        from jobs.services import create_job

        queue_job = create_job(
            "ai_generate",
            {"ai_job_id": ai_job.id},
            priority=10,
            max_retries=3,
            idempotency_key=f"ai_generate:{ai_job.id}",
        )
        ai_job.queue_job = queue_job
        ai_job.save(update_fields=["queue_job", "updated_at"])
        return ai_job
    return process_ai_job(ai_job)


def run_ai_generation(
    *,
    feature: str,
    prompt: str,
    input_payload: dict[str, Any] | None = None,
    workspace=None,
    site=None,
    requested_by=None,
    provider: str = "",
    model_name: str = "",
    metadata: dict[str, Any] | None = None,
) -> AIJob:
    return submit_ai_job(
        feature=feature,
        prompt=prompt,
        input_payload=input_payload,
        workspace=workspace,
        site=site,
        requested_by=requested_by,
        provider=provider,
        model_name=model_name,
        queue=False,
        metadata=metadata,
    )


__all__ = [
    "AIProviderResponse",
    "process_ai_job",
    "run_ai_generation",
    "submit_ai_job",
]
