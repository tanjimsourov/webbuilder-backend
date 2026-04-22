# NGINX sample

This folder contains a sample reverse proxy config for terminating public traffic and forwarding request IDs to the Django backend.

Use with:

```bash
docker compose --profile edge up -d nginx
```