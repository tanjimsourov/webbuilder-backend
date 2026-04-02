# Production Hardening Changelog

## 2026-04-02

### Django Settings and Environment Hardening
- Removed committed active `.env` usage from the repository and kept sample-only configuration in `.env.example`.
- Switched `DJANGO_DEBUG` default to `false` and added production-mode startup fail-fast validation gates.
- Removed insecure secret fallback patterns:
  - `DJANGO_SECRET_KEY` is mandatory and validated.
  - Payload and LibreCrawl secrets no longer inherit Django `SECRET_KEY`.
- Hardened host/origin configuration:
  - `DJANGO_ALLOWED_HOSTS` rejects wildcards and URL-style entries.
  - `DJANGO_CORS_ALLOWED_ORIGINS` and `DJANGO_CSRF_TRUSTED_ORIGINS` are strictly validated and wildcard-safe.
  - Production requires explicit CORS origins and matching CSRF trusted origins.
- Enforced production transport/session security requirements:
  - SSL redirect, HSTS, secure cookies, `USE_X_FORWARDED_HOST`, and `X_FRAME_OPTIONS=DENY`.
  - SameSite policy validation and secure-cookie coupling checks.
- Added production checks for database and cache safety:
  - SQLite disallowed when `DJANGO_DEBUG=false`.
  - Redis cache URL required in production (`DJANGO_CACHE_URL`).
- Added integration env safety checks for email, S3, Stripe, OpenAI, Namecheap, Payload, and LibreCrawl values.
- Added environment documentation: `ENVIRONMENT.md`.
- Added settings validation tests that execute `manage.py check` under controlled env permutations.

### Security and Configuration Hardening
- Hardened `config/settings.py` defaults for production:
  - Stronger `DJANGO_SECRET_KEY` validation and placeholder detection.
  - Enforced non-empty `DJANGO_ALLOWED_HOSTS` when `DJANGO_DEBUG=false`.
  - Added `DJANGO_AUTH_BOOTSTRAP_ENABLED`, `DJANGO_AUTH_BOOTSTRAP_TOKEN`, `DJANGO_AUTH_MAGIC_LOGIN_ENABLED`, and `DJANGO_METRICS_AUTH_TOKEN` controls.
  - Added auth/invitation throttle rate settings.
  - Added stricter secure header defaults and SameSite/Secure consistency guards.
  - Added upload file permission controls (`DJANGO_FILE_UPLOAD_PERMISSIONS`, `DJANGO_FILE_UPLOAD_DIRECTORY_PERMISSIONS`).
  - Companion services now default to disabled in production unless explicitly enabled.
  - Added S3 bucket validation when S3 storage is enabled.

### Auth and Endpoint Protection
- Added dedicated throttles for login/bootstrap/magic-login/invitation acceptance in `builder/throttles.py`.
- Hardened auth views in `builder/views.py`:
  - Login/bootstrap/magic-login now use dedicated throttles.
  - Bootstrap can be disabled and optionally token-protected.
  - Magic login is controlled by setting and now validates redirect safety.
- Hardened `MetricsView` to require a production token (`X-Metrics-Token`) and return `404` when protected.
- Added invitation throttle in `builder/workspace_views.py`.

### Authorization and Data Isolation Fixes
- Fixed media bulk actions in `builder/views.py`:
  - `bulk_delete` and `move_to_folder` now enforce site-scoped access checks for every asset ID.
  - Folder moves now validate site consistency.
- Tightened `BlockTemplateViewSet` query and write permissions to prevent cross-tenant modification and unsafe global template changes.

### Upload Security Improvements
- Strengthened `builder/upload_validation.py`:
  - Added filename sanitization checks.
  - Added MIME alias normalization.
  - Added server-side binary signature checks for common file types.
  - Added signature-vs-extension mismatch rejection.
  - Added stricter SVG document validation.

### Email Hosting Security and Correctness
- Replaced weak SHA-256 mailbox password hashing with Django `make_password` in:
  - `builder/serializers.py`
  - `builder/email_views.py`
- Fixed incorrect permission exception usage in `builder/email_views.py`.
- Added missing email task enum values in `builder/models.py` (`activate_mailbox`, `suspend_mailbox`).
- Added `get_user_workspaces()` helper in `builder/workspace_views.py` used by email APIs.

### Deployment and CI Safety
- Docker build now fails on `collectstatic` errors (`Dockerfile`).
- Docker Compose healthcheck now uses Python instead of unavailable `curl` (`docker-compose.yml`).
- Added baseline repository hygiene ignore rules (`.gitignore`).
- Added CI quality gates (`.github/workflows/ci.yml`) for:
  - `manage.py check`
  - `manage.py check --deploy --fail-level WARNING`
  - test suite
  - dependency audit (`pip-audit`)

### Verification Script Updates
- Updated `scripts/verify_deployment.py` and `scripts/smoke_test.py` to handle protected metrics endpoints with optional metrics token support.

### Tests Updated
- Expanded hardening coverage in `builder/tests.py` for:
  - production metrics token requirement
  - bootstrap disable gate
  - upload signature mismatch rejection
  - auth/invitation throttle scope assertions
  - cross-site media bulk delete authorization enforcement
- Adjusted brittle seed/platform-admin expectations to remain valid across seeded and non-seeded test environments.
