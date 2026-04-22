from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class EventMeta:
    event_id: str
    emitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str | None = None
    actor_id: str | None = None


@dataclass(frozen=True)
class DomainEvent:
    name: str
    meta: EventMeta
    payload: dict[str, Any]

