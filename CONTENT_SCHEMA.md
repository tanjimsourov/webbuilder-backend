# Content Schema

This document defines the backend content entities for CMS/blog/media flows.

## CMS entities (`cms`)

- `Page`: canonical page source (`builder_data`, `seo`, `page_settings`, render cache fields, publish state).
- `PageTranslation`: localized page variant keyed by `page + locale`.
- `ReusableSection`: reusable section schema library with draft/publish/archive lifecycle.
- `BlockTemplate`: reusable builder component templates (site/global scope, marketplace-ready status).
- `NavigationMenu`: header/footer/menu structures.
- `SiteShell`: header/footer assignment + shell settings.
- `URLRedirect`: source→target redirect rules.
- `RobotsTxt`: per-site robots override.
- `ThemeTemplate`: theme token and breakpoint presets for starter themes/marketplace packs.
- `MediaFolder`, `MediaAsset`: media library storage and metadata.
- `AssetUsageReference`: reverse references from content entities to media assets.
- `PublishSnapshot`: immutable publish snapshots for rollback.
- `PreviewToken`: expiring preview access tokens for draft/preview mode.

## Blog entities (`blog`)

- `BlogAuthor`: per-site author profile (display name, slug, avatar, bio).
- `Post`: content item with workflow states (`draft`, `in_review`, `scheduled`, `published`, `archived`), related posts, categories/tags, publish schedule.
- `PostCategory`, `PostTag`: taxonomy entities.
- `Comment`: moderation lifecycle (`pending`, `approved`, `rejected`, `spam`) + spam metadata.

## Website/runtime entities

- `core.Site.settings` stores website-level runtime config:
  - `seo` defaults
  - `branding` (`favicon`, `logo`, etc.)
  - `localization`
  - `deployment` metadata
  - runtime knobs (`robots`, `runtime`)
- `domains.Domain` stores custom domain ownership/verification status.

