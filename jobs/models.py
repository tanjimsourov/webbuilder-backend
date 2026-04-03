"""Jobs app models."""

from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class Job(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PRIORITY_LOW = 0
    PRIORITY_NORMAL = 5
    PRIORITY_HIGH = 10
    PRIORITY_URGENT = 20

    job_type = models.CharField(max_length=100)
    job_id = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict)
    result = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    priority = models.IntegerField(default=PRIORITY_NORMAL)
    scheduled_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    max_retries = models.IntegerField(default=3)
    retry_count = models.IntegerField(default=0)
    retry_delay_seconds = models.IntegerField(default=60)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-priority", "scheduled_at"]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["job_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.job_type}: {self.job_id} ({self.status})"
