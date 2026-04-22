from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_TRACING_INITIALIZED = False


def configure_tracing(config: Mapping[str, Any]) -> bool:
    global _TRACING_INITIALIZED
    if _TRACING_INITIALIZED:
        return True

    provider = str(config.get("TRACING_PROVIDER") or "none").strip().lower()
    if provider in {"", "none", "off", "disabled"}:
        return False
    if provider != "opentelemetry":
        logger.warning("Unsupported tracing provider '%s'; skipping.", provider)
        return False

    endpoint = str(config.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    service_name = str(config.get("OTEL_SERVICE_NAME") or "webbuilder-backend").strip()

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.warning("OpenTelemetry dependencies unavailable: %s", exc)
        return False

    try:
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter

            exporter = ConsoleSpanExporter()

        tracer_provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(tracer_provider)
        DjangoInstrumentor().instrument()
        _TRACING_INITIALIZED = True
        logger.info("Tracing initialized with provider=opentelemetry endpoint=%s", endpoint or "console")
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to initialize tracing: %s", exc)
        return False
