# Versioning Strategy

This repository follows **Semantic Versioning** (`MAJOR.MINOR.PATCH`) and Git tag-based releases.

## Rules

- `MAJOR`: breaking API/contract changes.
- `MINOR`: backward-compatible feature delivery.
- `PATCH`: backward-compatible bug fixes, hardening, and operational updates.

## Source of truth

- `VERSION` stores the next release base version.
- Release tags must be prefixed with `v` (example: `v0.1.0`).
- The effective release version is the Git tag, not branch name.

## Branching and release flow

1. Merge feature/fix PRs into `main`.
2. CI validates lint, checks, migrations, tests, and container build.
3. Release draft is generated from merged PR labels.
4. Maintainer bumps `VERSION` when preparing a release.
5. Maintainer creates a signed tag `vX.Y.Z` and pushes it.
6. Tag workflow publishes the GitHub release and container image.

## Changelog policy

- PRs should include a concise description of user impact.
- Label PRs for release notes grouping:
  - `feature`
  - `fix`
  - `security`
  - `ops`
  - `docs`

## Backports

- Critical fixes can be cherry-picked into a maintenance branch and released as `PATCH`.
- Maintenance branches must keep SemVer ordering and matching tags.
