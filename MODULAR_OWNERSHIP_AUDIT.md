# Modular Ownership Audit (Baseline)

Date: 2026-04-03
Phase: Baseline repository audit and execution-safe stabilization

This document records current module ownership so later migration phases can move remaining `builder` responsibilities in a controlled way.

## App Ownership Snapshot

| App | models | serializers | views | services | tasks | admin | migrations | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `core` | Local | Builder re-export | Builder-backed wrapper | Builder re-export | None | None | Local | Core data models migrated; API/service layer still builder-backed |
| `cms` | Local | Builder re-export | Builder-backed wrappers | Mostly builder-backed wrappers | None | None | Local | CMS models migrated; serializer/view/service logic still routed via builder |
| `commerce` | Local | Builder re-export | Builder-backed wrappers | Builder-backed wrappers | None | None | Local | Commerce models migrated; API/service logic still mostly builder-backed |
| `forms` | Local | Builder re-export | Builder-backed wrappers | Re-export to notifications service | None | None | Local | Form models migrated; runtime API still builder-backed |
| `blog` | Local | Builder re-export | Builder-backed wrappers | Builder-backed wrappers | None | None | Local | Blog models migrated; API/service layer still builder-backed |
| `analytics` | Local | Builder re-export | Builder-backed wrappers | Builder SEO services | None | None | Local | Analytics data models migrated; processing/API still builder-backed |
| `notifications` | Local | Builder re-export | Builder-backed wrapper (`WebhookViewSet`) | Builder-backed wrappers | None | None | Local | Notification data migrated; delivery/webhook internals still builder-backed |
| `jobs` | Local | Local | Local | Builder job bridge | Local | None | Local | Jobs app is active owner for task entry points, still calling builder jobs for some ops |
| `payments` | Local | Local | Local | Local | None | None | Local | Fully app-local for current payments flow |
| `domains` | Local | None | Builder-backed wrappers | Local + builder registrar integration | None | None | Local | Domain model/services migrated; registrar transport still delegated to builder |
| `email_hosting` | Local | Local | Local (uses shared workspace perms) | Local | None | None | Local | Email hosting app is largely app-local |
| `builder` | Legacy owner | Legacy owner | Legacy owner | Legacy owner | Legacy owner | Local admin | Legacy migrations | Still provides most serializer/view/service runtime behavior for transitional apps |

## Stale Import Cleanups Applied In This Phase

- `config/urls.py`: preview/public routes now import from app modules (`blog.views`, `cms.views`, `commerce.views`) instead of `builder.views`.
- `builder/urls.py`: domain viewsets now imported from `domains.views` instead of `cms.views`.
- `cms/views.py`: domain viewset compatibility exports now source from `domains.views` instead of `builder.views`.
- `forms/services.py`: `trigger_webhooks` now re-exported from `notifications.services` instead of direct `builder.services`.
- `email_hosting/views.py`: `SitePermissionMixin` now imported via `core.views` instead of direct `builder.views`.

## Remaining Builder-Owned Surface (For Later Phases)

- Most serializers in `core`, `cms`, `commerce`, `forms`, `blog`, `analytics`, and `notifications`.
- Most DRF viewset implementations across those same apps.
- Multiple service operations still delegated through `builder.services`, `builder.jobs`, `builder.seo_services`, and `builder.domain_services`.

## Startup/Import Stability Notes

- `python manage.py check` boots cleanly with development-safe env (`DJANGO_DEBUG=true`, non-placeholder `DJANGO_SECRET_KEY`).
- Full module import sweep is clean except for `jobs.celery` / `jobs.tasks` when `celery` is not installed in the active environment.
- `celery` is already declared in `requirements.txt`; no code fallback change was made in this phase.