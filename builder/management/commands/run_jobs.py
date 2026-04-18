"""
Management command to process background jobs.

Usage:
    python manage.py run_jobs              # Process pending jobs once
    python manage.py run_jobs --daemon     # Run continuously
    python manage.py run_jobs --cleanup    # Clean old completed jobs
"""

import signal
import time

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError


class Command(BaseCommand):
    help = "Process background jobs from the job queue"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--daemon",
            action="store_true",
            help="Run continuously as a daemon",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=5,
            help="Seconds between job checks in daemon mode (default: 5)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Number of jobs to process per batch (default: 10)",
        )
        parser.add_argument(
            "--cleanup",
            action="store_true",
            help="Clean up old completed/failed jobs",
        )
        parser.add_argument(
            "--cleanup-days",
            type=int,
            default=30,
            help="Delete jobs older than this many days (default: 30)",
        )

    def handle(self, *args, **options):
        if options["cleanup"]:
            self.cleanup_jobs(options["cleanup_days"])
            return

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        batch_size = options["batch_size"]
        interval = options["interval"]
        daemon = options["daemon"]

        self.stdout.write(
            self.style.SUCCESS(f"Job processor started (batch_size={batch_size}, daemon={daemon})")
        )

        if daemon:
            self.run_daemon(batch_size, interval)
        else:
            self.process_batch(batch_size)

    def signal_handler(self, signum, frame):
        self.stdout.write(self.style.WARNING("\nShutdown signal received, finishing current batch..."))
        self.running = False

    def run_daemon(self, batch_size: int, interval: int):
        """Run continuously, processing jobs at regular intervals."""
        while self.running:
            processed = self.process_batch(batch_size)
            if processed == 0:
                time.sleep(interval)
            else:
                time.sleep(0.1)

        self.stdout.write(self.style.SUCCESS("Job processor stopped"))

    def process_batch(self, batch_size: int) -> int:
        """Process a batch of pending jobs."""
        from builder.jobs import process_pending_jobs
        from django.db.utils import OperationalError

        try:
            processed = process_pending_jobs(batch_size=batch_size)
        except OperationalError as exc:
            raise CommandError(
                "Job tables are unavailable. Run migrations before starting run_jobs."
            ) from exc
        if processed > 0:
            self.stdout.write(f"Processed {processed} job(s)")
        return processed

    def cleanup_jobs(self, days: int):
        """Delete old completed/failed jobs."""
        from builder.jobs import cleanup_old_jobs

        deleted = cleanup_old_jobs(days=days)
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old job(s)"))
