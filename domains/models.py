"""Domain mapping and provisioning models."""

from __future__ import annotations

from django.db import models

from core.models import Site, TimeStampedModel


class DomainMapping(TimeStampedModel):
    site = models.ForeignKey(Site, related_name="domain_mappings", on_delete=models.CASCADE)
    domain = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(default=False)
    status = models.CharField(max_length=30, default="pending")
    dns_provider = models.CharField(max_length=50, blank=True)
    registrar = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["domain"]

    def __str__(self) -> str:
        return f"{self.site.slug} -> {self.domain} ({self.status})"


class SSLCertificate(TimeStampedModel):
    domain_mapping = models.OneToOneField(DomainMapping, related_name="certificate", on_delete=models.CASCADE)
    cert_file = models.TextField()
    key_file = models.TextField()
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["expires_at"]

    def __str__(self) -> str:
        return f"SSL for {self.domain_mapping.domain}"
