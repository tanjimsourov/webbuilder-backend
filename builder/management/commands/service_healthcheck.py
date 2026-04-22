from __future__ import annotations

import time

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from shared.cache.bootstrap import cache_is_healthy
from shared.db.bootstrap import database_is_healthy


class Command(BaseCommand):
    help = "Healthcheck command for app/worker/scheduler containers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--component",
            choices=["app", "worker", "scheduler"],
            default="app",
            help="Service component being checked.",
        )
        parser.add_argument("--check-cache", action="store_true", help="Require cache health in addition to DB.")
        parser.add_argument(
            "--max-heartbeat-age",
            type=int,
            default=300,
            help="Max scheduler heartbeat age in seconds.",
        )

    def handle(self, *args, **options):
        component = str(options["component"])
        check_cache = bool(options["check_cache"])
        max_heartbeat_age = max(30, int(options["max_heartbeat_age"]))

        if not database_is_healthy():
            raise CommandError("Database health check failed.")
        if check_cache and not cache_is_healthy():
            raise CommandError("Cache health check failed.")

        if component == "scheduler":
            heartbeat = cache.get("ops:scheduler:heartbeat")
            if heartbeat is None:
                raise CommandError("Scheduler heartbeat missing.")
            try:
                heartbeat_value = float(heartbeat)
            except (TypeError, ValueError) as exc:
                raise CommandError("Scheduler heartbeat value is invalid.") from exc
            age = time.time() - heartbeat_value
            if age > max_heartbeat_age:
                raise CommandError(f"Scheduler heartbeat stale: {int(age)}s")

        self.stdout.write(self.style.SUCCESS(f"{component} healthcheck OK"))
