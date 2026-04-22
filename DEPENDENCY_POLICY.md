# Dependency Policy

## Update cadence

- Security updates: apply immediately after triage.
- Routine dependency updates: weekly.
- Major-version upgrades: planned and validated in dedicated PRs.

## Approval rules

- Every dependency PR must pass CI and security scanning.
- Production-impacting upgrades require rollback notes in the PR.
- Cryptography/auth/session-related upgrades require explicit reviewer approval.

## Security scanning

- `pip-audit` runs in CI (`.github/workflows/ci.yml`) and in scheduled security workflow (`.github/workflows/security.yml`).
- CodeQL scanning runs on pushes/PRs and weekly schedule.

## Hashing and auth dependencies

- Keep `argon2-cffi` current within pinned major range.
- Any JWT/token library additions must enforce expiry, rotation, and revocation.

