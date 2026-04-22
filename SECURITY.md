# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately.

- Email: `security@smcwebbuilder.local` (replace with your real security mailbox in production)
- Subject: `SECURITY REPORT: <short title>`
- Include:
  - Affected endpoint/module
  - Reproduction steps
  - Impact assessment
  - Suggested remediation (if available)

Do not open public GitHub issues for active vulnerabilities.

## Response expectations

- Initial acknowledgment: within 2 business days
- Triage status update: within 5 business days
- Remediation target: based on severity and exploitability

## Supported versions

- `main`/`master` branch: supported
- Latest tagged release: supported
- Older releases: best-effort only, unless explicitly marked LTS

## Security controls in this repository

- Strict production settings validation
- Rate limiting and lockout controls
- Single-use security tokens for password reset/email verification
- Refresh token rotation and revocation
- Structured audit logging for sensitive actions
- Upload validation + optional malware scan hook

