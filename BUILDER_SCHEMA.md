# Builder Schema

`Page.builder_data` and `PageTranslation.builder_data` are the canonical visual-builder source payloads.

## Contract

- Schema version: `builder_schema_version` (`cms.page_schema.PAGE_SCHEMA_VERSION`).
- Normalization/validation: `cms.page_schema.normalize_page_content(...)`.
- Runtime projection:
  - `sections`
  - `section_contract` metadata
  - `component_registry`
  - render cache (`html`, `css`, `js`)

## Stored builder primitives

- Page-level:
  - metadata/title/slug/path
  - section tree
  - layout/styling tokens
  - SEO payload
  - page settings
- Reuse library:
  - `ReusableSection.schema`
  - `BlockTemplate.builder_data`
  - `ThemeTemplate.tokens` + `ThemeTemplate.breakpoints`

## Validation surfaces

- Create/update serializers normalize and reject invalid schema data.
- `POST /api/pages/{id}/validate_layout/` validates payload contracts with strict schema checks.
- Reusable section layout validation:
  - `POST /api/reusable-sections/{id}/validate_layout/`

