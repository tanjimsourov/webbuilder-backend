# jobs/

Domain app for durable, DB-backed background jobs.

- Owns the job queue models/migrations and job runner behaviors.
- The `job-runner` compose service runs `python manage.py run_jobs --daemon`.

