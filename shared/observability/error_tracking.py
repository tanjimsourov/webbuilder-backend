from __future__ import annotations

import logging
from typing import Mapping, Any

logger = logging.getLogger(__name__)


def configure_error_tracking(config: Mapping[str, Any]) -> bool:
    provider = str(config.get("ERROR_TRACKING_PROVIDER", "sentry") or "sentry").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return False
    if provider != "sentry":
        logger.warning("Unsupported error tracking provider '%s'; skipping.", provider)
        return False

    dsn = str(config.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    is_production = bool(config.get("IS_PRODUCTION"))
    if not is_production:
        return False

    traces_sample_rate = float(config.get("SENTRY_TRACES_SAMPLE_RATE", 0) or 0)
    profiles_sample_rate = float(config.get("SENTRY_PROFILES_SAMPLE_RATE", 0) or 0)
    environment = str(config.get("SENTRY_ENVIRONMENT") or "production")

    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("Sentry SDK unavailable: %s", exc)
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        integrations=[
            DjangoIntegration(transaction_style="url", middleware_spans=True),
            LoggingIntegration(level=None, event_level=None),
        ],
        traces_sample_rate=traces_sample_rate,
        profiles_sample_rate=profiles_sample_rate,
        send_default_pii=False,
        attach_stacktrace=True,
        traces_sampler=lambda ctx: (
            0
            if str(ctx.get("wsgi_environ", {}).get("PATH_INFO", "")).startswith("/api/health")
            else traces_sample_rate
        ),
    )
    logger.info("Error tracking initialized with provider=sentry")
    return True
