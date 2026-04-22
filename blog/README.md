# blog/

Domain app for blog content and public blog runtime endpoints.

- Owns blog models/migrations and routes in `blog/urls.py`.
- Public preview pages are mounted via `config/urls.py`.
- Includes author profiles, post workflow states, related posts, comment moderation, and spam-hook integration.
