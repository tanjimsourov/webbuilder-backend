# builder/

Legacy monolith app and platform/system surface area.

- Hosts platform/system endpoints such as `/api/health/`, auth bootstrap/login, platform admin, and AI helpers.
- Gradually extracting domain APIs into their owning apps; avoid adding new domain ownership here.
- Contains production logging formatter `builder/logging_config.py`.
- Still provides shared operational endpoints used by domain wrappers (search jobs, auth/session, platform admin).
