# shared/ai/

AI orchestration layer for admin-side generation features.

## Provider configuration

Set provider/runtime vars in `.env`:

- `AI_DEFAULT_PROVIDER=mock|openai|anthropic`
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`

Provider selection order:

1. Explicit provider in request payload
2. `AI_DEFAULT_PROVIDER`
3. First available provider fallback (`openai` → `anthropic` → `mock`)

## Supported generation features

- `page_outline`
- `blog_draft`
- `product_description`
- `seo_meta`
- `image_alt_text`
- `faq_schema`
- `section_composition`

## Quotas and metering

Quota model: `provider.AIUsageQuota`

- Scope: workspace/site + feature + period (`daily` or `monthly`)
- Limits: `max_requests`, `max_tokens`, `max_cost_usd`
- Activation flag: `is_active`

Usage model: `provider.AIUsageRecord`

- Stores provider/model, token usage, cost, actor, feature, and status.

Default quota env controls:

- `AI_DEFAULT_MAX_REQUESTS` (default `1000`)
- `AI_DEFAULT_MAX_TOKENS` (default `1000000`)
- `AI_DEFAULT_MAX_COST_USD` (default `50.00`)

## Job lifecycle and auditability

- Submission creates `provider.AIJob`.
- Long-running jobs are queued through `jobs` as `ai_generate`.
- Prompt and output moderation decisions are recorded in `provider.AIModerationLog`.
- Completion/failure emits site webhooks (`ai.job.completed`, `ai.job.failed`).
