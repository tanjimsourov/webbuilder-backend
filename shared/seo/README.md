# shared/seo/

Shared SEO normalization and composition utilities used across `cms`, `blog`, `commerce`, and `website`.

## SEO data flow

1. Editors store module-level SEO payloads (`seo` JSON fields) in CMS/blog/commerce entities.
2. Services call `normalize_seo_payload(...)` to enforce a consistent contract:
   - `meta_title`
   - `meta_description`
   - `canonical_url`
   - `open_graph`
   - `twitter`
   - `structured_data`
   - `robots.no_index` / `robots.no_follow`
3. `build_seo_payload(...)` merges defaults/fallbacks (title/description/canonical).
4. Public delivery layers consume normalized payloads for:
   - page/post/product metadata
   - sitemap filtering (exclude `no_index`)
   - robots output
5. `website` settings expose site-level SEO defaults that downstream modules inherit.

## Structured data abstraction

- `structured_data` accepts object or list payloads and is passed through normalized contracts.
- Rendering layers can safely emit JSON-LD from this field without module-specific branching.
