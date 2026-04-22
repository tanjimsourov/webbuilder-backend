# Observability Baseline

## Logging

- Structured JSON logs are enabled by default in non-debug mode (`DJANGO_LOG_FORMAT=json`).
- Request IDs are propagated through `X-Request-ID` and included in logs.
- Sensitive fields are redacted in log payloads.

## Error tracking

- `ERROR_TRACKING_PROVIDER=sentry` enables Sentry through a provider abstraction.
- `SENTRY_DSN` is required for production error capture.

## Tracing hooks

- `TRACING_PROVIDER=opentelemetry` enables optional OpenTelemetry bootstrap.
- `OTEL_EXPORTER_OTLP_ENDPOINT` controls OTLP export target.
- If tracing libraries are missing, startup continues with tracing disabled.

## Health and metrics

- HTTP probes: `/api/health/`, `/api/ready/`, `/api/live/`, `/api/version/`.
- Metrics endpoint: `/api/metrics/` (token-protected in production).
- Worker/scheduler probes: `python manage.py service_healthcheck ...`.
