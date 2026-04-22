from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from django.utils.text import slugify

from shared.errors.exceptions import ValidationAppError


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str


def require_fields(payload: Mapping[str, Any], *fields: str) -> None:
    missing = [field for field in fields if payload.get(field) in (None, "", [], {}, ())]
    if missing:
        raise ValidationAppError("Missing required fields.", details={"missing": missing})


def unique_slug(
    *,
    value: str,
    queryset,
    slug_field: str = "slug",
    fallback: str = "item",
    max_length: int = 180,
) -> str:
    base_slug = slugify(value or "") or fallback
    base_slug = base_slug[:max_length].strip("-") or fallback
    candidate = base_slug
    suffix = 2
    while queryset.filter(**{slug_field: candidate}).exists():
        suffix_text = f"-{suffix}"
        trimmed = base_slug[: max(1, max_length - len(suffix_text))].rstrip("-")
        candidate = f"{trimmed}{suffix_text}"
        suffix += 1
    return candidate
