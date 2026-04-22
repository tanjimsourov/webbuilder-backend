# domains/

Domain app for domain provisioning and request host resolution.

- Owns domain models/migrations and routes in `domains/urls.py`.
- Provider integrations should avoid embedding secrets in code and should rely on validated env config.

