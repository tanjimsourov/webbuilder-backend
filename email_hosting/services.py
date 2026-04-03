"""Service layer for email domain, mailbox, and alias provisioning."""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from domains import services as domain_services
from email_hosting.models import EmailDomain, EmailProvisioningTask, MailAlias, Mailbox

logger = logging.getLogger(__name__)


class EmailProvisioningError(RuntimeError):
    """Raised when an email provisioning operation fails."""


@dataclass
class DNSRecordCheck:
    expected: str
    observed: list[str]
    ready: bool
    detail: str = ""


def _task_for_id(task_id: int | None) -> EmailProvisioningTask | None:
    if not task_id:
        return None
    return EmailProvisioningTask.objects.filter(pk=task_id).first()


def _create_task(
    *,
    workspace_id: int,
    task_type: str,
    target_id: int,
    payload: dict[str, Any] | None = None,
) -> EmailProvisioningTask:
    return EmailProvisioningTask.objects.create(
        workspace_id=workspace_id,
        task_type=task_type,
        target_id=str(target_id),
        payload=payload or {},
    )


def _set_task_running(task: EmailProvisioningTask | None, message: str = "") -> None:
    if not task:
        return
    task.status = EmailProvisioningTask.Status.RUNNING
    task.message = message
    task.save(update_fields=["status", "message", "updated_at"])


def _set_task_success(task: EmailProvisioningTask | None, message: str = "", payload: dict[str, Any] | None = None) -> None:
    if not task:
        return
    task.status = EmailProvisioningTask.Status.SUCCESS
    if message:
        task.message = message
    if payload is not None:
        task.payload = payload
    task.save(update_fields=["status", "message", "payload", "updated_at"])


def _set_task_failed(task: EmailProvisioningTask | None, exc: Exception) -> None:
    if not task:
        return
    task.status = EmailProvisioningTask.Status.FAILED
    task.message = str(exc)
    task.save(update_fields=["status", "message", "updated_at"])


def _queue_task(task_name: str, *args: Any) -> bool:
    try:
        from jobs import tasks as job_tasks

        task = getattr(job_tasks, task_name)
        task.delay(*args)
        return True
    except Exception:
        logger.warning("Unable to queue Celery task %s; running inline fallback.", task_name, exc_info=True)
        return False


def _dkim_public_key(domain_name: str, token: str) -> str:
    configured = (getattr(settings, "EMAIL_HOSTING_DKIM_PUBLIC_KEY", "") or "").strip()
    if configured:
        return configured
    return hashlib.sha256(f"{domain_name}:{token}".encode("utf-8")).hexdigest()


def _default_dns_records(domain_name: str, verification_token: str) -> dict[str, str]:
    mx_host = (getattr(settings, "EMAIL_HOSTING_MX_HOST", "mail.{domain}") or "mail.{domain}").format(
        domain=domain_name
    )
    spf = (
        getattr(settings, "EMAIL_HOSTING_SPF_TEMPLATE", "v=spf1 mx include:{domain} ~all")
        or "v=spf1 mx include:{domain} ~all"
    ).format(domain=domain_name)
    dmarc = (
        getattr(settings, "EMAIL_HOSTING_DMARC_TEMPLATE", "v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}")
        or "v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}"
    ).format(domain=domain_name)
    dkim = f"v=DKIM1; k=rsa; p={_dkim_public_key(domain_name, verification_token)}"
    return {
        "mx_record": mx_host.strip(),
        "spf_record": spf.strip(),
        "dkim_record": dkim.strip(),
        "dmarc_record": dmarc.strip(),
    }


def _dns_lookup(name: str, record_type: str, timeout: int) -> list[str]:
    query = urllib.parse.urlencode({"name": name, "type": record_type})
    url = f"https://dns.google/resolve?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    records: list[str] = []
    for answer in data.get("Answer", []):
        payload = str(answer.get("data") or "").strip()
        if not payload:
            continue
        if record_type.upper() == "TXT":
            payload = payload.replace('" "', "").strip('"')
        records.append(payload)
    return records


def _record_matches(expected: str, observed: list[str], *, prefix_ok: str = "") -> DNSRecordCheck:
    expected_clean = (expected or "").strip()
    observed_clean = [item.strip() for item in observed if item.strip()]
    if expected_clean and any(expected_clean.lower() == item.lower() for item in observed_clean):
        return DNSRecordCheck(expected=expected_clean, observed=observed_clean, ready=True)
    if prefix_ok and any(item.lower().startswith(prefix_ok.lower()) for item in observed_clean):
        return DNSRecordCheck(
            expected=expected_clean,
            observed=observed_clean,
            ready=True,
            detail=f"Matched fallback prefix {prefix_ok}.",
        )
    return DNSRecordCheck(expected=expected_clean, observed=observed_clean, ready=False)


def _mailbox_address(mailbox: Mailbox) -> str:
    return f"{mailbox.local_part}@{mailbox.domain.name}".lower()


def _coerce_domain(domain_or_id: EmailDomain | int) -> EmailDomain:
    if isinstance(domain_or_id, EmailDomain):
        return domain_or_id
    return EmailDomain.objects.select_related("site", "workspace").get(pk=domain_or_id)


def _coerce_mailbox(mailbox_or_id: Mailbox | int) -> Mailbox:
    if isinstance(mailbox_or_id, Mailbox):
        return mailbox_or_id
    return Mailbox.objects.select_related("domain", "site", "workspace").get(pk=mailbox_or_id)


def _coerce_alias(alias_or_id: MailAlias | int) -> MailAlias:
    if isinstance(alias_or_id, MailAlias):
        return alias_or_id
    return MailAlias.objects.select_related("destination_mailbox", "site", "workspace").get(pk=alias_or_id)


class BaseEmailProvider(ABC):
    """Abstract provider adapter for email hosting operations."""

    @abstractmethod
    def provision_domain(self, domain: EmailDomain) -> dict[str, str]:
        ...

    @abstractmethod
    def create_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_mailbox(self, mailbox: Mailbox, *, is_active: bool | None = None, password_hash: str | None = None) -> dict[str, Any]:
        ...

    @abstractmethod
    def delete_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        ...

    @abstractmethod
    def create_alias(self, alias: MailAlias) -> dict[str, Any]:
        ...

    @abstractmethod
    def update_alias(self, alias: MailAlias, *, is_active: bool) -> dict[str, Any]:
        ...

    @abstractmethod
    def delete_alias(self, alias: MailAlias) -> dict[str, Any]:
        ...


class LocalEmailProvider(BaseEmailProvider):
    """Development/local provider that executes provisioning semantics in-app."""

    def provision_domain(self, domain: EmailDomain) -> dict[str, str]:
        return _default_dns_records(domain.name, str(domain.verification_token))

    def create_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        return {"provider": "local", "mailbox": _mailbox_address(mailbox), "active": mailbox.is_active}

    def update_mailbox(self, mailbox: Mailbox, *, is_active: bool | None = None, password_hash: str | None = None) -> dict[str, Any]:
        payload = {"provider": "local", "mailbox": _mailbox_address(mailbox)}
        if is_active is not None:
            payload["active"] = is_active
        if password_hash:
            payload["password_updated"] = True
        return payload

    def delete_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        return {"provider": "local", "deleted_mailbox": _mailbox_address(mailbox)}

    def create_alias(self, alias: MailAlias) -> dict[str, Any]:
        return {
            "provider": "local",
            "source": alias.source_address,
            "destination": alias.destination_mailbox.email_address,
            "active": alias.active,
        }

    def update_alias(self, alias: MailAlias, *, is_active: bool) -> dict[str, Any]:
        return {"provider": "local", "source": alias.source_address, "active": is_active}

    def delete_alias(self, alias: MailAlias) -> dict[str, Any]:
        return {"provider": "local", "deleted_alias": alias.source_address}


class ApiEmailProvider(BaseEmailProvider):
    """HTTP adapter for external mail providers."""

    def __init__(self, base_url: str, api_token: str, timeout: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        raw = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                body = response.read().decode("utf-8") or "{}"
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise EmailProvisioningError(f"Provider request failed ({exc.code}): {detail}") from exc
        except Exception as exc:  # pragma: no cover - network dependency
            raise EmailProvisioningError(f"Provider request failed: {exc}") from exc

    def provision_domain(self, domain: EmailDomain) -> dict[str, str]:
        result = self._request(
            "POST",
            "/domains",
            payload={"domain": domain.name, "verification_token": str(domain.verification_token)},
        )
        records = result.get("dns_records") or {}
        if not isinstance(records, dict):
            raise EmailProvisioningError("Provider returned invalid DNS records payload.")
        defaults = _default_dns_records(domain.name, str(domain.verification_token))
        defaults.update({k: str(v).strip() for k, v in records.items() if v})
        return defaults

    def create_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        return self._request(
            "POST",
            "/mailboxes",
            payload={
                "address": _mailbox_address(mailbox),
                "password_hash": mailbox.password_hash,
                "quota_mb": mailbox.quota_mb,
                "active": mailbox.is_active,
            },
        )

    def update_mailbox(self, mailbox: Mailbox, *, is_active: bool | None = None, password_hash: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if is_active is not None:
            payload["active"] = is_active
        if password_hash:
            payload["password_hash"] = password_hash
        return self._request("PATCH", f"/mailboxes/{urllib.parse.quote(_mailbox_address(mailbox))}", payload=payload)

    def delete_mailbox(self, mailbox: Mailbox) -> dict[str, Any]:
        return self._request("DELETE", f"/mailboxes/{urllib.parse.quote(_mailbox_address(mailbox))}")

    def create_alias(self, alias: MailAlias) -> dict[str, Any]:
        return self._request(
            "POST",
            "/aliases",
            payload={
                "source": alias.source_address,
                "destination": alias.destination_mailbox.email_address,
                "active": alias.active,
            },
        )

    def update_alias(self, alias: MailAlias, *, is_active: bool) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/aliases/{urllib.parse.quote(alias.source_address)}",
            payload={"active": is_active},
        )

    def delete_alias(self, alias: MailAlias) -> dict[str, Any]:
        return self._request("DELETE", f"/aliases/{urllib.parse.quote(alias.source_address)}")


def _provider() -> BaseEmailProvider:
    provider_name = (getattr(settings, "EMAIL_HOSTING_PROVIDER", "local") or "local").lower()
    if provider_name == "api":
        base_url = (getattr(settings, "EMAIL_HOSTING_API_BASE_URL", "") or "").strip()
        token = (getattr(settings, "EMAIL_HOSTING_API_TOKEN", "") or "").strip()
        timeout = int(getattr(settings, "EMAIL_HOSTING_API_TIMEOUT", 20))
        if not base_url or not token:
            raise EmailProvisioningError("EMAIL_HOSTING_API_BASE_URL and EMAIL_HOSTING_API_TOKEN are required.")
        return ApiEmailProvider(base_url=base_url, api_token=token, timeout=timeout)
    return LocalEmailProvider()


def get_domain_dns_status(domain_or_id: EmailDomain | int) -> dict[str, Any]:
    domain = _coerce_domain(domain_or_id)
    timeout = int(getattr(settings, "EMAIL_HOSTING_DNS_TIMEOUT", 8))
    dkim_selector = (getattr(settings, "EMAIL_HOSTING_DKIM_SELECTOR", "k1") or "k1").strip()

    mx_records = _dns_lookup(domain.name, "MX", timeout=timeout)
    root_txt = _dns_lookup(domain.name, "TXT", timeout=timeout)
    dkim_txt = _dns_lookup(f"{dkim_selector}._domainkey.{domain.name}", "TXT", timeout=timeout)
    dmarc_txt = _dns_lookup(f"_dmarc.{domain.name}", "TXT", timeout=timeout)
    ownership_ok, ownership_detail = domain_services.verify_domain_ownership(domain.name, str(domain.verification_token))

    checks = {
        "mx": _record_matches(domain.mx_record, mx_records),
        "spf": _record_matches(domain.spf_record, root_txt, prefix_ok="v=spf1"),
        "dkim": _record_matches(domain.dkim_record, dkim_txt, prefix_ok="v=DKIM1"),
        "dmarc": _record_matches(domain.dmarc_record, dmarc_txt, prefix_ok="v=DMARC1"),
        "ownership": DNSRecordCheck(
            expected=f"webbuilder-verify={domain.verification_token}",
            observed=[ownership_detail] if ownership_detail else [],
            ready=ownership_ok,
            detail=ownership_detail,
        ),
    }
    ready = all(check.ready for check in checks.values())

    return {
        "domain": domain.name,
        "ready": ready,
        "records": {
            key: {
                "ready": value.ready,
                "expected": value.expected,
                "observed": value.observed,
                "detail": value.detail,
            }
            for key, value in checks.items()
        },
    }


def create_email_domain(
    name: str,
    workspace,
    site,
    *,
    queue_provisioning: bool = True,
    queue_verification: bool = True,
) -> tuple[EmailDomain, EmailProvisioningTask]:
    """Create an email domain and start provisioning workflows."""
    domain_name = name.strip().lower().rstrip(".")
    if site.workspace_id != workspace.id:
        raise EmailProvisioningError("Site and workspace mismatch.")

    with transaction.atomic():
        domain = EmailDomain.objects.create(
            name=domain_name,
            workspace=workspace,
            site=site,
            status=EmailDomain.DomainStatus.PENDING,
        )
        domain_fields = _default_dns_records(domain.name, str(domain.verification_token))
        for field, value in domain_fields.items():
            setattr(domain, field, value)
        domain.save(update_fields=["mx_record", "spf_record", "dkim_record", "dmarc_record", "updated_at"])
        domain_services.ensure_domain_portfolio_entry(site, domain.name, str(domain.verification_token))

        task = _create_task(
            workspace_id=workspace.id,
            task_type=EmailProvisioningTask.TaskType.CREATE_DOMAIN,
            target_id=domain.id,
            payload={"domain": domain.name},
        )

    if queue_provisioning and _queue_task("provision_email_domain_task", domain.id, task.id):
        return domain, task

    provision_email_domain(domain.id, provisioning_task_id=task.id, queue_verification=queue_verification)
    return domain, task


def provision_email_domain(
    domain_or_id: EmailDomain | int,
    *,
    provisioning_task_id: int | None = None,
    queue_verification: bool = True,
) -> EmailDomain:
    """Provision domain resources in the configured provider."""
    domain = _coerce_domain(domain_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Provisioning email domain.")

    try:
        records = _provider().provision_domain(domain)
        for key in ("mx_record", "spf_record", "dkim_record", "dmarc_record"):
            if records.get(key):
                setattr(domain, key, records[key].strip())
        domain.status = EmailDomain.DomainStatus.PENDING
        domain.save(update_fields=["mx_record", "spf_record", "dkim_record", "dmarc_record", "status", "updated_at"])

        domain_services.ensure_domain_portfolio_entry(domain.site, domain.name, str(domain.verification_token))
        _set_task_success(task, "Email domain provisioning completed.", payload={"domain": domain.name, "records": records})

        if queue_verification:
            queue_domain_verification(domain.id)
        return domain
    except Exception as exc:
        domain.status = EmailDomain.DomainStatus.FAILED
        domain.save(update_fields=["status", "updated_at"])
        _set_task_failed(task, exc)
        raise


def queue_domain_verification(email_domain_id: int) -> EmailProvisioningTask:
    domain = _coerce_domain(email_domain_id)
    task = _create_task(
        workspace_id=domain.workspace_id,
        task_type=EmailProvisioningTask.TaskType.VERIFY_DOMAIN,
        target_id=domain.id,
        payload={"domain": domain.name},
    )
    if not _queue_task("verify_email_domain_task", domain.id, task.id):
        verify_email_domain(domain.id, provisioning_task_id=task.id)
    return task


def verify_email_domain(domain_or_id: EmailDomain | int, *, provisioning_task_id: int | None = None) -> dict[str, Any]:
    """Evaluate DNS readiness and update domain status."""
    domain = _coerce_domain(domain_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Verifying DNS readiness.")
    domain.status = EmailDomain.DomainStatus.VERIFYING
    domain.save(update_fields=["status", "updated_at"])

    try:
        dns_status = get_domain_dns_status(domain)
        if dns_status["ready"]:
            domain.status = EmailDomain.DomainStatus.ACTIVE
            domain.verified_at = timezone.now()
            domain_services.mark_domain_verified_for_email(domain.site, domain.name)
        else:
            domain.status = EmailDomain.DomainStatus.PENDING
        domain.save(update_fields=["status", "verified_at", "updated_at"])
        _set_task_success(task, "DNS verification completed.", payload=dns_status)
        return dns_status
    except Exception as exc:
        domain.status = EmailDomain.DomainStatus.FAILED
        domain.save(update_fields=["status", "updated_at"])
        _set_task_failed(task, exc)
        raise


def create_mailbox(
    domain: EmailDomain,
    local_part: str,
    password: str,
    user=None,
    *,
    quota_mb: int = 1024,
    is_active: bool = True,
    queue_provisioning: bool = True,
) -> tuple[Mailbox, EmailProvisioningTask]:
    """Create mailbox and provision it in the configured provider."""
    cleaned_local = local_part.strip().lower()
    require_active = bool(getattr(settings, "EMAIL_HOSTING_REQUIRE_ACTIVE_DOMAIN", True))
    if require_active and domain.status != EmailDomain.DomainStatus.ACTIVE:
        raise EmailProvisioningError("Email domain must be active before creating mailboxes.")

    with transaction.atomic():
        mailbox = Mailbox.objects.create(
            domain=domain,
            site=domain.site,
            workspace=domain.workspace,
            local_part=cleaned_local,
            password_hash=make_password(password),
            quota_mb=quota_mb,
            user=user,
            is_active=is_active,
        )
        task = _create_task(
            workspace_id=mailbox.workspace_id,
            task_type=EmailProvisioningTask.TaskType.CREATE_MAILBOX,
            target_id=mailbox.id,
            payload={"email": mailbox.email_address},
        )

    if queue_provisioning and _queue_task("provision_mailbox_task", mailbox.id, task.id):
        return mailbox, task

    provision_mailbox(mailbox.id, provisioning_task_id=task.id)
    return mailbox, task


def provision_mailbox(mailbox_or_id: Mailbox | int, *, provisioning_task_id: int | None = None) -> Mailbox:
    mailbox = _coerce_mailbox(mailbox_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Provisioning mailbox.")
    try:
        result = _provider().create_mailbox(mailbox)
        _set_task_success(task, "Mailbox provisioned.", payload={"result": result})
        return mailbox
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def sync_mailbox(mailbox_or_id: Mailbox | int, *, provisioning_task_id: int | None = None) -> Mailbox:
    mailbox = _coerce_mailbox(mailbox_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Syncing mailbox state.")
    try:
        result = _provider().update_mailbox(
            mailbox,
            is_active=mailbox.is_active,
            password_hash=mailbox.password_hash,
        )
        _set_task_success(task, "Mailbox sync completed.", payload={"result": result})
        return mailbox
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def update_mailbox_password(mailbox_or_id: Mailbox | int, new_password: str) -> tuple[Mailbox, EmailProvisioningTask]:
    mailbox = _coerce_mailbox(mailbox_or_id)
    mailbox.password_hash = make_password(new_password)
    mailbox.save(update_fields=["password_hash", "updated_at"])
    task = _create_task(
        workspace_id=mailbox.workspace_id,
        task_type=EmailProvisioningTask.TaskType.UPDATE_MAILBOX,
        target_id=mailbox.id,
        payload={"action": "password_reset", "email": mailbox.email_address},
    )
    if not _queue_task("sync_mailbox_task", mailbox.id, task.id):
        sync_mailbox(mailbox.id, provisioning_task_id=task.id)
    return mailbox, task


def set_mailbox_active(mailbox_or_id: Mailbox | int, *, is_active: bool) -> tuple[Mailbox, EmailProvisioningTask]:
    mailbox = _coerce_mailbox(mailbox_or_id)
    mailbox.is_active = is_active
    mailbox.save(update_fields=["is_active", "updated_at"])
    task = _create_task(
        workspace_id=mailbox.workspace_id,
        task_type=EmailProvisioningTask.TaskType.UPDATE_MAILBOX,
        target_id=mailbox.id,
        payload={"action": "set_active", "active": is_active, "email": mailbox.email_address},
    )
    if not _queue_task("sync_mailbox_task", mailbox.id, task.id):
        sync_mailbox(mailbox.id, provisioning_task_id=task.id)
    return mailbox, task


def disable_mailbox(mailbox_or_id: Mailbox | int) -> tuple[Mailbox, EmailProvisioningTask]:
    return set_mailbox_active(mailbox_or_id, is_active=False)


def delete_mailbox(mailbox_or_id: Mailbox | int) -> EmailProvisioningTask:
    mailbox = _coerce_mailbox(mailbox_or_id)
    task = _create_task(
        workspace_id=mailbox.workspace_id,
        task_type=EmailProvisioningTask.TaskType.DELETE_MAILBOX,
        target_id=mailbox.id,
        payload={"email": mailbox.email_address},
    )
    _set_task_running(task, "Deleting mailbox.")
    try:
        provider = _provider()
        aliases = list(mailbox.aliases.all())
        for alias in aliases:
            provider.delete_alias(alias)
        result = provider.delete_mailbox(mailbox)
        mailbox.delete()
        _set_task_success(task, "Mailbox deleted.", payload={"result": result})
        return task
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def create_alias(
    domain: EmailDomain,
    source: str,
    destination_mailbox: Mailbox,
    *,
    active: bool = True,
    queue_provisioning: bool = True,
) -> tuple[MailAlias, EmailProvisioningTask]:
    """Create alias and provision forwarding in provider."""
    source_address = source.strip().lower()
    if "@" not in source_address:
        raise EmailProvisioningError("Alias source must be a full email address.")
    if not source_address.endswith(f"@{domain.name}"):
        raise EmailProvisioningError("Alias source must belong to the selected domain.")
    if destination_mailbox.workspace_id != domain.workspace_id:
        raise EmailProvisioningError("Destination mailbox belongs to another workspace.")

    with transaction.atomic():
        alias = MailAlias.objects.create(
            site=domain.site,
            workspace=domain.workspace,
            source_address=source_address,
            destination_mailbox=destination_mailbox,
            active=active,
        )
        task = _create_task(
            workspace_id=alias.workspace_id,
            task_type=EmailProvisioningTask.TaskType.CREATE_ALIAS,
            target_id=alias.id,
            payload={"source": alias.source_address, "destination": destination_mailbox.email_address},
        )

    if queue_provisioning and _queue_task("provision_alias_task", alias.id, task.id):
        return alias, task

    provision_alias(alias.id, provisioning_task_id=task.id)
    return alias, task


def provision_alias(alias_or_id: MailAlias | int, *, provisioning_task_id: int | None = None) -> MailAlias:
    alias = _coerce_alias(alias_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Provisioning alias.")
    try:
        result = _provider().create_alias(alias)
        _set_task_success(task, "Alias provisioned.", payload={"result": result})
        return alias
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def sync_alias(alias_or_id: MailAlias | int, *, provisioning_task_id: int | None = None) -> MailAlias:
    alias = _coerce_alias(alias_or_id)
    task = _task_for_id(provisioning_task_id)
    _set_task_running(task, "Syncing alias state.")
    try:
        result = _provider().update_alias(alias, is_active=alias.active)
        _set_task_success(task, "Alias sync completed.", payload={"result": result})
        return alias
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def set_alias_active(alias_or_id: MailAlias | int, *, is_active: bool) -> tuple[MailAlias, EmailProvisioningTask]:
    alias = _coerce_alias(alias_or_id)
    alias.active = is_active
    alias.save(update_fields=["active", "updated_at"])
    task = _create_task(
        workspace_id=alias.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_ALIAS,
        target_id=alias.id,
        payload={"action": "set_active", "active": is_active, "source": alias.source_address},
    )
    if not _queue_task("sync_alias_task", alias.id, task.id):
        sync_alias(alias.id, provisioning_task_id=task.id)
    return alias, task


def disable_alias(alias_or_id: MailAlias | int) -> tuple[MailAlias, EmailProvisioningTask]:
    return set_alias_active(alias_or_id, is_active=False)


def delete_alias(alias_or_id: MailAlias | int) -> EmailProvisioningTask:
    alias = _coerce_alias(alias_or_id)
    task = _create_task(
        workspace_id=alias.workspace_id,
        task_type=EmailProvisioningTask.TaskType.DELETE_ALIAS,
        target_id=alias.id,
        payload={"source": alias.source_address},
    )
    _set_task_running(task, "Deleting alias.")
    try:
        result = _provider().delete_alias(alias)
        alias.delete()
        _set_task_success(task, "Alias deleted.", payload={"result": result})
        return task
    except Exception as exc:
        _set_task_failed(task, exc)
        raise


def queue_domain_provisioning(email_domain_id: int) -> EmailProvisioningTask:
    domain = _coerce_domain(email_domain_id)
    task = _create_task(
        workspace_id=domain.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_DOMAIN,
        target_id=domain.id,
        payload={"domain": domain.name},
    )
    if not _queue_task("provision_email_domain_task", domain.id, task.id):
        provision_email_domain(domain.id, provisioning_task_id=task.id)
    return task


def queue_mailbox_provisioning(mailbox_id: int) -> EmailProvisioningTask:
    mailbox = _coerce_mailbox(mailbox_id)
    task = _create_task(
        workspace_id=mailbox.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_MAILBOX,
        target_id=mailbox.id,
        payload={"email": mailbox.email_address},
    )
    if not _queue_task("provision_mailbox_task", mailbox.id, task.id):
        provision_mailbox(mailbox.id, provisioning_task_id=task.id)
    return task


def queue_alias_provisioning(alias_id: int) -> EmailProvisioningTask:
    alias = _coerce_alias(alias_id)
    task = _create_task(
        workspace_id=alias.workspace_id,
        task_type=EmailProvisioningTask.TaskType.CREATE_ALIAS,
        target_id=alias.id,
        payload={"source": alias.source_address},
    )
    if not _queue_task("provision_alias_task", alias.id, task.id):
        provision_alias(alias.id, provisioning_task_id=task.id)
    return task


__all__ = [
    "EmailProvisioningError",
    "create_alias",
    "create_email_domain",
    "create_mailbox",
    "delete_alias",
    "delete_mailbox",
    "disable_alias",
    "disable_mailbox",
    "get_domain_dns_status",
    "provision_alias",
    "provision_email_domain",
    "provision_mailbox",
    "queue_alias_provisioning",
    "queue_domain_provisioning",
    "queue_domain_verification",
    "queue_mailbox_provisioning",
    "set_alias_active",
    "set_mailbox_active",
    "sync_alias",
    "sync_mailbox",
    "update_mailbox_password",
    "verify_email_domain",
]
