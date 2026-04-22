# Publish Workflow

## Content lifecycle

- Pages:
  - draft editing (`save_builder`)
  - publish (`publish`)
  - schedule future publish (`schedule`)
  - unpublish (`unpublish`)
  - revision restore (`revisions/{id}/restore`)
- Posts:
  - workflow statuses (`draft`, `in_review`, `scheduled`, `published`, `archived`)
  - moderation and schedule endpoints
- Products:
  - draft/published lifecycle with snapshots

## Snapshots and rollback

- Publish and unpublish actions create `PublishSnapshot` rows.
- Snapshots can be restored from:
  - `POST /api/publish-snapshots/{id}/restore/`
- Page revision history continues to work via `PageRevision`.

## Preview mode

- Create expiring preview tokens:
  - `POST /api/preview-tokens/`
- Resolve preview token into page payload:
  - `POST /api/preview-tokens/resolve/`
- Revoke token:
  - `POST /api/preview-tokens/{id}/revoke/`

## Runtime cache and revalidation

- CMS/blog/website runtime endpoints set explicit public caching headers.
- Page publishes enqueue runtime revalidation jobs for affected routes.

## Event emission

Webhooks are emitted for major content events, including:

- `page.published`, `page.updated`
- `post.published`, `post.updated`, `post.archived`
- `media.asset.created`, `media.asset.updated`, `media.asset.deleted`, `media.asset.restored`
- `section.published`, `section.unpublished`

