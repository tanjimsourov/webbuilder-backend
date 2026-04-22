"""Domain mapping and provisioning models."""

from __future__ import annotations

from django.db import models

from core.models import Site, TimeStampedModel


class DomainMapping(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
        (STATUS_FAILED, "Failed"),
    ]

    site = models.ForeignKey(Site, related_name="domain_mappings", on_delete=models.CASCADE)
    domain = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(default=False)
    status = models.CharField(max_length=30, default=STATUS_PENDING)
    dns_provider = models.CharField(max_length=50, blank=True)
    registrar = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["domain"]

    def __str__(self) -> str:
        return f"{self.site.slug} -> {self.domain} ({self.status})"

    @property
    def is_public_active(self) -> bool:
        return (self.status or "").strip().lower() == self.STATUS_ACTIVE


class SSLCertificate(TimeStampedModel):
    domain_mapping = models.OneToOneField(DomainMapping, related_name="certificate", on_delete=models.CASCADE)
    cert_file = models.TextField()
    key_file = models.TextField()
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["expires_at"]

    def __str__(self) -> str:
        return f"SSL for {self.domain_mapping.domain}"


class DomainContact(TimeStampedModel):
    ROLE_REGISTRANT = "registrant"
    ROLE_ADMIN = "admin"
    ROLE_TECH = "tech"
    ROLE_BILLING = "billing"
    ROLE_CHOICES = [
        (ROLE_REGISTRANT, "Registrant"),
        (ROLE_ADMIN, "Administrative"),
        (ROLE_TECH, "Technical"),
        (ROLE_BILLING, "Billing"),
    ]

    site = models.ForeignKey(Site, related_name="domain_contacts", on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_REGISTRANT)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    organization = models.CharField(max_length=140, blank=True)
    address1 = models.CharField(max_length=255, blank=True)
    address2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2 country code")

    class Meta:
        ordering = ["role", "last_name"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.first_name} {self.last_name} ({self.role})"


class Domain(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_FAILED = "failed"
    STATUS_REQUESTED = "requested"
    STATUS_VERIFYING = "verifying"
    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_VERIFYING, "Verifying"),
        (STATUS_PENDING, "Pending Verification"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_FAILED, "Verification Failed"),
    ]

    REG_STATUS_UNREGISTERED = "unregistered"
    REG_STATUS_ACTIVE = "active"
    REG_STATUS_EXPIRED = "expired"
    REG_STATUS_PENDING_TRANSFER = "pending_transfer"
    REG_STATUS_PENDING_DELETE = "pending_delete"
    REG_STATUS_LOCKED = "locked"
    REG_STATUS_CHOICES = [
        (REG_STATUS_UNREGISTERED, "Unregistered / External"),
        (REG_STATUS_ACTIVE, "Active"),
        (REG_STATUS_EXPIRED, "Expired"),
        (REG_STATUS_PENDING_TRANSFER, "Pending Transfer"),
        (REG_STATUS_PENDING_DELETE, "Pending Delete"),
        (REG_STATUS_LOCKED, "Locked"),
    ]

    VERIFY_METHOD_DNS_TXT = "dns_txt"
    VERIFY_METHOD_FILE = "file"
    VERIFY_METHOD_CHOICES = [
        (VERIFY_METHOD_DNS_TXT, "DNS TXT Record"),
        (VERIFY_METHOD_FILE, "File Upload"),
    ]

    site = models.ForeignKey(Site, related_name="domains", on_delete=models.CASCADE)
    domain_name = models.CharField(max_length=255, unique=True)
    is_primary = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    verification_token = models.CharField(max_length=100, blank=True)
    verification_method = models.CharField(
        max_length=40, choices=VERIFY_METHOD_CHOICES, default=VERIFY_METHOD_DNS_TXT, blank=True
    )
    verification_state = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    verified_at = models.DateTimeField(blank=True, null=True)
    last_verification_attempt = models.DateTimeField(blank=True, null=True)
    verification_error = models.TextField(blank=True)
    registration_status = models.CharField(
        max_length=30, choices=REG_STATUS_CHOICES, default=REG_STATUS_UNREGISTERED
    )
    registrar = models.CharField(max_length=140, blank=True)
    registrar_account = models.CharField(max_length=140, blank=True)
    registered_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    auto_renew = models.BooleanField(default=True)
    privacy_enabled = models.BooleanField(default=False)
    transfer_lock = models.BooleanField(default=True)
    auth_code = models.CharField(max_length=255, blank=True)
    ssl_enabled = models.BooleanField(default=False)
    ssl_status = models.CharField(
        max_length=30,
        choices=[
            ("disabled", "Disabled"),
            ("pending", "Pending"),
            ("provisioning", "Provisioning"),
            ("active", "Active"),
            ("renewal_failed", "Renewal failed"),
            ("revoked", "Revoked"),
        ],
        default="disabled",
    )
    ssl_expires_at = models.DateTimeField(blank=True, null=True)
    dns_records = models.JSONField(default=list, blank=True)
    nameservers = models.JSONField(default=list, blank=True)
    whois_data = models.JSONField(default=dict, blank=True)
    whois_fetched_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    registrant_contact = models.ForeignKey(
        DomainContact,
        related_name="domains_as_registrant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-is_primary", "domain_name"]

    def __str__(self) -> str:
        return f"{self.site.name}: {self.domain_name}"


class SSLCertificateProvisioning(TimeStampedModel):
    STATUS_PENDING = "pending"
    STATUS_PROVISIONING = "provisioning"
    STATUS_ACTIVE = "active"
    STATUS_RENEWAL_FAILED = "renewal_failed"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROVISIONING, "Provisioning"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_RENEWAL_FAILED, "Renewal failed"),
        (STATUS_REVOKED, "Revoked"),
    ]

    domain = models.ForeignKey(Domain, related_name="ssl_provisionings", on_delete=models.CASCADE)
    provider = models.CharField(max_length=80, default="internal")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider_reference = models.CharField(max_length=255, blank=True)
    certificate_chain = models.TextField(blank=True)
    private_key_reference = models.CharField(max_length=255, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["domain", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.domain.domain_name}:{self.status}"


class DomainAvailability(models.Model):
    domain_name = models.CharField(max_length=255)
    available = models.BooleanField()
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default="USD", blank=True)
    registrar = models.CharField(max_length=140, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["domain_name", "checked_at"]),
        ]

    def __str__(self) -> str:
        status = "available" if self.available else "taken"
        return f"{self.domain_name}: {status}"
