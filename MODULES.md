# Modules

This repo is a modular Django backend. Each module below is a Django app unless noted otherwise.

## Platform/system

- `config/`: Django project configuration and process entrypoints.
- `shared/` (package): cross-cutting infrastructure (env aliases, auth/token/audit services, request context, logging helpers, DTO contracts, upload hardening helpers, search abstraction).
- `builder/`: legacy monolith app; hosts platform/system endpoints (`/api/health/`, auth bootstrap/login, platform admin) and acts as an extraction staging area.
- `deploy/`: deployment guides, reverse proxy examples, backup/restore procedures.
- `ops/`: runbooks, incident checklists, rollback and migration playbooks.

## Domains

- `core/`: workspaces, sites, and core platform primitives.
- `cms/`: pages, templates, navigation, rendering/public preview.
- `blog/`: blog posts and public feed/views.
- `website/`: site runtime settings, domain verification wrappers, robots/sitemap/publish metadata APIs.
- `provider/`: pluggable infrastructure provider abstractions (storage/image/email/search/dns/payment/shipping/tax).
- `commerce/`: catalog, carts, checkout sessions, orders, fulfillment, payments/refunds, inventory reservations, and public shop APIs.
- `payments/`: Stripe integration and billing primitives.
- `forms/`: form definitions and submissions.
- `analytics/`: analytics storage and API surfaces.
- `notifications/`: webhook and notification delivery.
- `jobs/`: durable DB-backed job queue and runners.
- `domains/`: domain provisioning/routing helpers (and provider integrations).
- `email_hosting/`: email hosting flows and APIs.

`posts/` is not currently a separate app; post entities are owned by `blog/`.
