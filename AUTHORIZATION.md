# Identity, Access, and Multi-Tenancy

This backend implements an enterprise-style identity and authorization baseline for a modular website-builder platform.

## Identity model

- `auth.User` remains the authentication principal.
- `core.UserAccount` stores profile/compliance/security state:
  - unique normalized email
  - `email_verified_at`
  - `mfa_enabled`
  - avatar/profile fields (`display_name`, `avatar_url`, `profile_bio`, locale/timezone)
  - status flags (`active`, `pending`, `locked`, `suspended`, `deleted`)
  - compliance/consent fields (`terms_accepted_at`, `privacy_accepted_at`, `data_processing_consent_at`, `marketing_opt_in`)
- `core.UserSecurityState` stores lockout/password/token-version state.

## Auth flows

Implemented endpoints (under `/api/auth/`):

- register/login/logout
- token issue/refresh/revoke (short-lived access token + rotating refresh token)
- forgot/reset password (single-use expiring token)
- email verification request/confirm (+ resend alias)
- password change
- optional social auth via `shared/auth/social.py`

## MFA

- TOTP setup and verification (`MFATOTPDevice`)
- backup recovery codes (`MFARecoveryCode`)
- MFA login challenge with one-time token (`SecurityToken` purpose `mfa_challenge`)

## Sessions and devices

- `UserSession` stores per-device session state and metadata.
- APIs support:
  - list active sessions
  - revoke a specific session (session id or device id)
  - revoke all other sessions

## Token model

- Access token: signed short-lived token, validated against `UserSecurityState.access_token_version`.
- Refresh token: hashed, stored in `SecurityToken` with rotation and revocation support.
- Password reset/change increments access token version and revokes refresh/session state.

## Tenancy and RBAC

### Tenant hierarchy

- `Workspace` is the tenant boundary.
- A user can belong to many workspaces via `WorkspaceMembership`.
- `Site` belongs to one workspace.
- Site-scoped membership is modeled via `SiteMembership`.

### Roles

- Platform: super admin (`is_superuser`) and support operator (`UserAccount.is_support_agent`).
- Workspace roles: owner, admin, editor, author, analyst, support, billing manager, viewer.
- Site roles: site owner, editor, author, analyst, support, billing manager, viewer.

### Permissions and contracts

- Canonical permission checks are centralized in `shared/policies/access.py`.
- Seeded RBAC contract tables:
  - `RBACRole`
  - `RBACPermission`
  - `RBACRolePermission`

## Invitations and membership lifecycle

- `WorkspaceInvitation` supports pending/accepted/declined/expired states.
- Invitation acceptance validates token expiry and email ownership before membership creation.
- Platform-admin APIs support workspace and site membership lifecycle operations.

## API keys and scopes

- Personal automation keys are stored hashed in `PersonalAPIKey`.
- Supported scopes:
  - `sites:read`, `sites:write`
  - `content:read`, `content:write`
  - `commerce:read`, `commerce:write`
  - `analytics:read`
  - `forms:read`, `forms:write`
  - `domains:read`, `domains:write`
  - `webhooks:read`, `webhooks:write`
- API key auth is enforced by `shared/auth/api_key_auth.py` and scoped access checks in `SitePermissionMixin`.

## Impersonation and auditability

- Impersonation is restricted to super admins/support operators.
- Full audit trail is stored in:
  - `ImpersonationAudit`
  - `SecurityAuditLog`

Sensitive auth actions (login/logout/password/MFA/token/api-key/impersonation/membership changes) are logged through `shared/auth/audit.py` with secret redaction.
