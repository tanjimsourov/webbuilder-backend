# Security Baseline

## Auth model

- Primary auth: Django session authentication (`SessionAuthentication`).
- CSRF protection: enabled via Django CSRF middleware; auth-mutating endpoints are CSRF-protected.
- Password hashing: Argon2 primary hasher with PBKDF2 fallbacks.
- Login abuse protection: per-IP/user throttling + exponential backoff + account lockout state.

## Token model

- Access token: short-lived signed token (`AUTH_ACCESS_TOKEN_TTL_SECONDS`).
- Refresh token: server-stored hashed token (`core.SecurityToken`, `purpose=refresh`).
- Rotation: refresh token is rotated on refresh requests.
- Revocation: refresh tokens can be revoked and are revoked on password reset.
- Single-use flows: email verification and password reset tokens are single-use + expiring.

## Upload model

- Extension allowlist and blocked-extension denylist.
- MIME-type + signature verification for supported file formats.
- SVG safety checks for script/event-handler rejection.
- Size limits per file kind.
- Randomized server-side filenames (`shared.storage.uploads.secure_media_upload_path`).
- Optional malware scan hook via `MALWARE_SCAN_COMMAND`.

## Storage isolation

- Default media root is isolated under `DJANGO_MEDIA_ROOT` (defaults to `./var/media`).
- Uploads are written to an object-style path (`objects/media/...`) rather than executable code paths.
- Optional S3-compatible object storage for production (`DJANGO_USE_S3_STORAGE=true`).

## RBAC model

- Workspace roles: `owner`, `admin`, `editor`, `viewer`.
- Site/resource access is filtered by workspace membership and role checks.
- Admin-only surfaces use explicit `IsPlatformOwner` permissions.
- Public runtime endpoints remain read-only and avoid privileged mutations.

## Audit logging model

- Sensitive actions are persisted in `core.SecurityAuditLog`.
- Current coverage includes:
  - login/logout/bootstrap
  - token issue/refresh/revoke
  - password reset request/confirm
  - email verification request/confirm
  - workspace role changes
  - site publish/unpublish/theme-settings updates
  - payment intent + refund actions
  - API key create/revoke
- Logs include actor, action, target, request id, IP, user-agent, success flag, and redacted metadata.

