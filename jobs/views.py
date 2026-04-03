"""Jobs domain views."""

from __future__ import annotations

from rest_framework import mixins, viewsets

from jobs.models import Job
from jobs.serializers import JobSerializer


class JobViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only job endpoints."""

    queryset = Job.objects.all().order_by("-priority", "scheduled_at")
    serializer_class = JobSerializer


__all__ = [
    "JobViewSet",
]
