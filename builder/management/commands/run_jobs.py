"""
Management command to process background jobs.

Usage:
    python manage.py run_jobs              # Process pending jobs once
    python manage.py run_jobs --daemon     # Run continuously
    python manage.py run_jobs --cleanup    # Clean old completed jobs
"""

import time
import signal
import sys
from django.core.management.base import BaseCommand


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
        from builder.models import Job

        if options["cleanup"]:
            self.cleanup_jobs(options["cleanup_days"])
            return

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        batch_size = options["batch_size"]
        interval = options["interval"]
        daemon = options["daemon"]

        self.stdout.write(self.style.SUCCESS(
            f"Job processor started (batch_size={batch_size}, daemon={daemon})"
        ))

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
                # No jobs processed, wait before checking again
                time.sleep(interval)
            else:
                # Jobs were processed, check immediately for more
                time.sleep(0.1)

        self.stdout.write(self.style.SUCCESS("Job processor stopped"))

    def process_batch(self, batch_size: int) -> int:
        """Process a batch of pending jobs."""
        from builder.models import Job
        from django.utils import timezone
        import traceback

        # Import job handlers to register them
        try:
            from builder import jobs as job_handlers
        except ImportError:
            pass

        now = timezone.now()

        # Get jobs that are ready to run
        pending_jobs = Job.objects.filter(
            status=Job.STATUS_PENDING,
            scheduled_at__lte=now,
        ).order_by("-priority", "scheduled_at")[:batch_size]

        processed = 0

        for job in pending_jobs:
            if not self.running:
                break

            self.stdout.write(f"Processing job: {job.job_type} ({job.job_id})")

            try:
                self.process_job(job)
                processed += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Completed: {job.status}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Error: {e}"))

        if processed > 0:
            self.stdout.write(f"Processed {processed} job(s)")

        return processed

    def process_job(self, job):
        """Process a single job."""
        from builder.models import Job
        from django.utils import timezone
        import traceback

        # Get handler
        from builder.jobs import get_job_handler
        handler = get_job_handler(job.job_type)

        if not handler:
            job.status = Job.STATUS_FAILED
            job.last_error = f"No handler for job type: {job.job_type}"
            job.save(update_fields=["status", "last_error", "updated_at"])
            return

        # Mark as running
        job.status = Job.STATUS_RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at", "updated_at"])

        try:
            result = handler(job)
            job.result = result or {}
            job.status = Job.STATUS_COMPLETED
            job.completed_at = timezone.now()

        except Exception as e:
            job.last_error = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            job.retry_count += 1

            if job.retry_count < job.max_retries:
                # Schedule retry with exponential backoff
                from datetime import timedelta
                job.status = Job.STATUS_PENDING
                job.scheduled_at = timezone.now() + timedelta(seconds=job.retry_delay_seconds * job.retry_count)
            else:
                job.status = Job.STATUS_FAILED
                job.completed_at = timezone.now()

        job.save()

    def cleanup_jobs(self, days: int):
        """Delete old completed/failed jobs."""
        from builder.models import Job
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = Job.objects.filter(
            status__in=[Job.STATUS_COMPLETED, Job.STATUS_FAILED, Job.STATUS_CANCELLED],
            updated_at__lt=cutoff,
        ).delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old job(s)"))
