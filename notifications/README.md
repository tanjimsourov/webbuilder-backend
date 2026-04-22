# notifications/

Domain app for notifications and webhook delivery.

- Owns notification/webhook models/migrations and routes in `notifications/urls.py`.
- Webhook delivery should be transaction-aware and avoid private/loopback targets in production by default.

