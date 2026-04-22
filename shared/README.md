# shared/

`shared/` is a **framework-agnostic** core layer for cross-cutting concerns that should not live inside any single Django app.

## Contents

- `shared/config/`: env aliases and configuration helpers.
- `shared/auth/`: security audit, lockout, and token services.
- `shared/http/`: request context middleware and response helpers.
- `shared/storage/`: secure upload path + malware scan hook.
- `shared/logger/`: request-context logging filter.
- `shared/errors/`: standard exception model (used by services; optionally mapped at the API layer).
- `shared/db/`, `shared/cache/`: lightweight health/bootstrap helpers.
- `shared/events/`: message/event contracts (dataclasses).
- `shared/contracts/`: small DTO validation helpers.
- `shared/ai/`: multi-provider AI orchestration, moderation, quotas, and usage metering.
- `shared/queue/`: queue helper wrappers for AI/search/webhook background work.
- `shared/search/`: search indexing abstraction used across modules.
- `shared/seo/`: SEO metadata normalization and structured-data contract utilities.
- `shared/payments/`: payment gateway facade + idempotency helpers for commerce.
