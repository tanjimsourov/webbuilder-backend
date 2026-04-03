"""Jobs domain serializers."""

from __future__ import annotations

from rest_framework import serializers

from jobs.models import Job


class JobSerializer(serializers.ModelSerializer):
    """Read serializer for background jobs."""

    class Meta:
        model = Job
        fields = "__all__"
        read_only_fields = "__all__"


__all__ = [
    "JobSerializer",
]
