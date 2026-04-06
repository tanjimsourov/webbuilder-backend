"""Forms domain service exports."""

from notifications.services import trigger_webhooks  # noqa: F401

__all__ = [
    "trigger_webhooks",
]
