from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from typing import Callable

from django.core.cache import cache
from django.core.management.base import BaseCommand


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SchedulerTask:
    name: str
    interval_seconds: int
    runner: Callable[[], dict]


class Command(BaseCommand):
    help = "Run operational scheduler loops for publish cleanup and rollups."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def add_arguments(self, parser):
        parser.add_argument("--daemon", action="store_true", help="Run continuously.")
        parser.add_argument("--interval", type=int, default=60, help="Main loop tick seconds (daemon mode).")

    def handle(self, *args, **options):
        tasks = self._build_tasks()
        loop_interval = max(5, int(options["interval"]))

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.stdout.write(
            self.style.SUCCESS(
                "Scheduler started with tasks: "
                + ", ".join(f"{task.name}={task.interval_seconds}s" for task in tasks)
            )
        )

        if options["daemon"]:
            self._run_daemon(tasks, loop_interval=loop_interval)
        else:
            self._run_cycle(tasks, force=True)
            self._heartbeat(loop_interval)

    def _signal_handler(self, signum, frame):
        self.stdout.write(self.style.WARNING("\nScheduler shutdown signal received."))
        self.running = False

    def _build_tasks(self) -> list[SchedulerTask]:
        return [
            SchedulerTask(
                name="scheduled_publish",
                interval_seconds=max(30, _int_env("SCHEDULER_PUBLISH_INTERVAL_SECONDS", 60)),
                runner=self._task_scheduled_publish,
            ),
            SchedulerTask(
                name="ai_retention_cleanup",
                interval_seconds=max(300, _int_env("SCHEDULER_AI_CLEANUP_INTERVAL_SECONDS", 3600)),
                runner=self._task_ai_cleanup,
            ),
            SchedulerTask(
                name="token_cleanup",
                interval_seconds=max(120, _int_env("SCHEDULER_TOKEN_CLEANUP_INTERVAL_SECONDS", 900)),
                runner=self._task_token_cleanup,
            ),
            SchedulerTask(
                name="analytics_rollup",
                interval_seconds=max(120, _int_env("SCHEDULER_ANALYTICS_ROLLUP_INTERVAL_SECONDS", 300)),
                runner=self._task_analytics_rollup,
            ),
        ]

    def _run_daemon(self, tasks: list[SchedulerTask], *, loop_interval: int) -> None:
        while self.running:
            self._run_cycle(tasks, force=False)
            self._heartbeat(loop_interval)
            time.sleep(loop_interval)
        self.stdout.write(self.style.SUCCESS("Scheduler stopped"))

    def _run_cycle(self, tasks: list[SchedulerTask], *, force: bool) -> None:
        now = time.monotonic()
        last_run = cache.get("ops:scheduler:last-run") or {}
        if not isinstance(last_run, dict):
            last_run = {}

        for task in tasks:
            previous = float(last_run.get(task.name, 0) or 0)
            due = force or (now - previous) >= task.interval_seconds
            if not due:
                continue
            try:
                result = task.runner()
                self.stdout.write(f"{task.name}: {result}")
            except Exception as exc:  # pragma: no cover - operational safety
                self.stderr.write(self.style.ERROR(f"{task.name} failed: {type(exc).__name__}: {exc}"))
            last_run[task.name] = now

        cache.set("ops:scheduler:last-run", last_run, timeout=max(task.interval_seconds for task in tasks) * 10)

    def _heartbeat(self, loop_interval: int) -> None:
        cache.set("ops:scheduler:heartbeat", str(time.time()), timeout=max(loop_interval * 6, 300))

    def _task_scheduled_publish(self) -> dict:
        from builder.jobs import process_scheduled_content

        queued = process_scheduled_content()
        return {"queued": int(queued)}

    def _task_ai_cleanup(self) -> dict:
        from provider.maintenance import cleanup_ai_generation_records

        retention_days = max(1, _int_env("SCHEDULER_AI_RETENTION_DAYS", 90))
        return cleanup_ai_generation_records(retention_days=retention_days)

    def _task_token_cleanup(self) -> dict:
        from shared.auth.maintenance import cleanup_security_tokens

        retention_days = max(1, _int_env("SCHEDULER_TOKEN_RETENTION_DAYS", 30))
        return cleanup_security_tokens(retention_days=retention_days)

    def _task_analytics_rollup(self) -> dict:
        from analytics.services import run_analytics_rollups

        days_back = max(1, _int_env("SCHEDULER_ANALYTICS_ROLLUP_DAYS_BACK", 2))
        return run_analytics_rollups(days_back=days_back)
