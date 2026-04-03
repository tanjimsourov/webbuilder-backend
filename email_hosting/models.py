"""Email hosting models migrated from builder.models."""

import uuid

from django.contrib.auth import get_user_model
from django.db import models

from core.models import Site, TimeStampedModel, Workspace


class EmailDomain(TimeStampedModel):
    class DomainStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFYING = "verifying", "Verifying"
        ACTIVE = "active", "Active"
        FAILED = "failed", "Failed"
        SUSPENDED = "suspended", "Suspended"

    site = models.ForeignKey(
        Site,
        related_name="email_domains",
        on_delete=models.CASCADE,
        help_text="Site that owns this email domain",
    )
    workspace = models.ForeignKey(
        Workspace,
        related_name="email_domains",
        on_delete=models.CASCADE,
        help_text="Workspace that owns this domain",
    )
    name = models.CharField(
        max_length=253,
        unique=True,
        help_text="Fully qualified domain name for email hosting",
    )
    status = models.CharField(
        max_length=20,
        choices=DomainStatus.choices,
        default=DomainStatus.PENDING,
        help_text="Current verification state of the email domain",
    )
    verification_token = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        help_text="Token used for DNS verification",
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when domain was verified",
    )
    mx_record = models.CharField(
        max_length=255,
        blank=True,
        help_text="MX record for email routing",
    )
    spf_record = models.TextField(
        blank=True,
        help_text="SPF record for email authentication",
    )
    dkim_record = models.TextField(
        blank=True,
        help_text="DKIM record for email signing",
    )
    dmarc_record = models.TextField(
        blank=True,
        help_text="DMARC record for email policy",
    )

    class Meta:
        ordering = ["name"]
        unique_together = ("site", "name")

    @property
    def dkim_selector(self) -> str:
        return "k1"

    @property
    def verification_txt_value(self) -> str:
        return f"webbuilder-verify={self.verification_token}"

    @property
    def expected_dns_records(self) -> dict[str, str]:
        return {
            "mx": self.mx_record,
            "spf": self.spf_record,
            "dkim": self.dkim_record,
            "dmarc": self.dmarc_record,
            "ownership": self.verification_txt_value,
        }

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class Mailbox(TimeStampedModel):
    workspace = models.ForeignKey(
        Workspace,
        related_name="mailboxes",
        on_delete=models.CASCADE,
    )
    site = models.ForeignKey(
        Site,
        related_name="mailboxes",
        on_delete=models.CASCADE,
    )
    domain = models.ForeignKey(
        EmailDomain,
        related_name="mailboxes",
        on_delete=models.CASCADE,
    )
    local_part = models.CharField(
        max_length=64,
        help_text="Username part before @",
    )
    password_hash = models.CharField(
        max_length=128,
        help_text="Hashed password for authentication",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether mailbox is active",
    )
    quota_mb = models.PositiveIntegerField(
        default=1024,
        help_text="Storage quota in megabytes",
    )
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last successful login timestamp",
    )
    user = models.ForeignKey(
        get_user_model(),
        related_name="mailboxes",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Associated user account",
    )

    class Meta:
        ordering = ["local_part"]
        unique_together = ("domain", "local_part")

    @property
    def email_address(self) -> str:
        return f"{self.local_part}@{self.domain.name}"

    def __str__(self) -> str:
        return self.email_address


class MailAlias(TimeStampedModel):
    workspace = models.ForeignKey(
        Workspace,
        related_name="mail_aliases",
        on_delete=models.CASCADE,
    )
    site = models.ForeignKey(
        Site,
        related_name="mail_aliases",
        on_delete=models.CASCADE,
    )
    source_address = models.EmailField(
        help_text="Source email address for alias",
    )
    destination_mailbox = models.ForeignKey(
        Mailbox,
        related_name="aliases",
        on_delete=models.CASCADE,
        help_text="Mailbox to forward emails to",
    )
    active = models.BooleanField(
        default=True,
        help_text="Whether alias is active",
    )

    class Meta:
        ordering = ["source_address"]
        unique_together = ("source_address", "destination_mailbox")

    def __str__(self) -> str:
        return f"{self.source_address} -> {self.destination_mailbox.email_address}"


class EmailProvisioningTask(TimeStampedModel):
    class TaskType(models.TextChoices):
        CREATE_DOMAIN = "create_domain", "Create Domain"
        DELETE_DOMAIN = "delete_domain", "Delete Domain"
        VERIFY_DOMAIN = "verify_domain", "Verify Domain"
        CREATE_MAILBOX = "create_mailbox", "Create Mailbox"
        DELETE_MAILBOX = "delete_mailbox", "Delete Mailbox"
        UPDATE_MAILBOX = "update_mailbox", "Update Mailbox"
        CREATE_ALIAS = "create_alias", "Create Alias"
        DELETE_ALIAS = "delete_alias", "Delete Alias"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    workspace = models.ForeignKey(
        Workspace,
        related_name="email_provisioning_tasks",
        on_delete=models.CASCADE,
    )
    task_type = models.CharField(
        max_length=30,
        choices=TaskType.choices,
        help_text="Type of provisioning task",
    )
    target_id = models.CharField(
        max_length=64,
        help_text="ID of the object being provisioned",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current task status",
    )
    message = models.TextField(
        blank=True,
        help_text="Task result or error message",
    )
    payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Additional task data",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.task_type} ({self.status})"
