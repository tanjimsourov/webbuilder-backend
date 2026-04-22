# analytics/

Domain app for first-party analytics ingestion, storage, and dashboard querying.

## Event taxonomy

- `page_view`: page hits and route-level traffic.
- `event`: generic custom event tracking.
- `conversion`: conversion milestones (signup/purchase/etc.).
- `funnel`: named funnel-step events (`funnel.*` convention).
- `commerce` events live in `CommerceAnalyticsEvent`:
  - `product.view`
  - `cart.add`
  - `checkout.begin`
  - `order.purchase`
  - `order.refund`

## Data model

- `AnalyticsSession`: per-site session isolation, UTM fields, device/browser/os dimensions.
- `AnalyticsEvent`: immutable event stream linked to optional sessions.
- `SearchDocument`: internal search document store (DB fallback index).
- `CommerceAnalyticsEvent`: commerce funnel telemetry stream.

## Ingestion and privacy

- Public ingestion endpoint: `POST /api/analytics/ingest/<site_slug>/`.
- Basic bot filtering uses user-agent signatures and rejects known crawlers.
- IP privacy is preserved by storing:
  - salted hash (`ip_hash`)
  - truncated prefix (`ip_prefix`)
- Raw client IP is not persisted.

## Query endpoints

- Summary: `GET /api/analytics/sites/<site_id>/summary/?period=daily|weekly|monthly&days=30`
- Funnel: `POST /api/analytics/sites/<site_id>/funnel/`
- Read APIs: sessions/events/search documents via authenticated site-scoped endpoints.
