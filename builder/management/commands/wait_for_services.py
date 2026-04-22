from __future__ import annotations

import os
import time

from django.core.management.base import BaseCommand, CommandError

from shared.cache.bootstrap import cache_is_healthy
from shared.db.bootstrap import database_is_healthy


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Wait for required backing services (database/cache) before startup."

    def add_arguments(self, parser):
        parser.add_argument("--db", action="store_true", help="Wait for database readiness.")
        parser.add_argument("--cache", action="store_true", help="Wait for cache readiness.")
        parser.add_argument("--timeout", type=int, default=60, help="Max wait timeout in seconds.")
        parser.add_argument("--sleep", type=float, default=2.0, help="Sleep between probes in seconds.")

    def handle(self, *args, **options):
        wait_db = bool(options["db"]) or _env_bool("DJANGO_WAIT_FOR_DB", False)
        wait_cache = bool(options["cache"]) or _env_bool("DJANGO_WAIT_FOR_CACHE", False)
        timeout = max(1, int(options["timeout"]))
        sleep_seconds = max(0.2, float(options["sleep"]))

        if not wait_db and not wait_cache:
            self.stdout.write("No wait targets selected; skipping dependency wait.")
            return

        start = time.monotonic()
        while True:
            db_ok = True if not wait_db else database_is_healthy()
            cache_ok = True if not wait_cache else cache_is_healthy()
            if db_ok and cache_ok:
                waited = round(time.monotonic() - start, 2)
                self.stdout.write(self.style.SUCCESS(f"Dependencies ready after {waited}s"))
                return

            if time.monotonic() - start >= timeout:
                state = {"database": db_ok, "cache": cache_ok}
                raise CommandError(f"Timed out waiting for dependencies: {state}")

            time.sleep(sleep_seconds)
