from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


DEFAULT_BLOCKED_TERMS = {
    "credit card number",
    "ssn",
    "social security number",
    "private key",
    "api key leak",
    "exploit payload",
    "malware source",
    "xss payload",
}


@dataclass(frozen=True)
class ModerationResult:
    blocked: bool
    reasons: list[str]
    sanitized_text: str


def _normalize_terms(terms: Iterable[str]) -> set[str]:
    return {str(term or "").strip().lower() for term in terms if str(term or "").strip()}


def moderate_text(
    text: str,
    *,
    blocked_terms: Iterable[str] | None = None,
    max_length: int = 20_000,
) -> ModerationResult:
    value = str(text or "")
    sanitized = value[:max_length]
    reasons: list[str] = []
    lowered = sanitized.lower()
    for token in sorted(_normalize_terms(blocked_terms or DEFAULT_BLOCKED_TERMS)):
        if token and token in lowered:
            reasons.append(f"blocked_term:{token}")
    blocked = bool(reasons)
    return ModerationResult(blocked=blocked, reasons=reasons, sanitized_text=sanitized)
