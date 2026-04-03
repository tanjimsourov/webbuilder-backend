"""Service functions for domain provisioning and SSL automation.

Chosen integrations:
- Registrar: Namecheap (via ``builder.domain_services.NamecheapClient``)
- DNS: Namecheap DNS host records API
- TLS: Let's Encrypt via certbot CLI
"""

from __future__ import annotations

import logging
import shutil
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from django.conf import settings
from django.utils.dateparse import parse_date, parse_datetime

from builder import domain_services as builder_domain_services
from domains.models import Domain, DomainAvailability, DomainContact, DomainMapping, SSLCertificate

logger = logging.getLogger(__name__)


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_iso_or_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = parse_datetime(value)
    if dt is not None:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    d = parse_date(value)
    if d is not None:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return None


def _contact_payload(contact: DomainContact) -> dict[str, str]:
    phone = contact.phone or "+1.5555555555"
    state = contact.state or "NA"
    postal_code = contact.postal_code or "00000"
    country = (contact.country or "US").upper()
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "phone": phone,
        "organization": contact.organization or "",
        "address1": contact.address1 or "Not Provided",
        "city": contact.city or "Not Provided",
        "state": state,
        "postal_code": postal_code,
        "country": country,
    }


def _settings_nameservers() -> list[str]:
    raw = (getattr(settings, "DOMAIN_DEFAULT_NAMESERVERS", "") or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_dns_hosts(domain: Domain) -> list[dict[str, str]]:
    apex_ip = (getattr(settings, "DOMAIN_DEFAULT_A_RECORD", "") or "").strip()
    root_target = (getattr(settings, "DOMAIN_DEFAULT_ROOT_CNAME", "") or "").strip()
    www_target = (getattr(settings, "DOMAIN_DEFAULT_WWW_CNAME", "") or "@").strip()

    hosts: list[dict[str, str]] = []
    if apex_ip:
        hosts.append({"name": "@", "type": "A", "address": apex_ip, "ttl": "300"})
    elif root_target:
        hosts.append({"name": "@", "type": "CNAME", "address": root_target, "ttl": "300"})

    if www_target:
        hosts.append({"name": "www", "type": "CNAME", "address": www_target, "ttl": "300"})

    if domain.verification_token and domain.verification_method == Domain.VERIFY_METHOD_DNS_TXT:
        hosts.append(
            {
                "name": "_webbuilder-verify",
                "type": "TXT",
                "address": f"webbuilder-verify={domain.verification_token}",
                "ttl": "300",
            }
        )
    return hosts


def _register_with_namecheap(domain: Domain, contact: DomainContact) -> dict[str, Any]:
    client = builder_domain_services.get_namecheap_client_from_settings()
    if client is None:
        raise RuntimeError("Namecheap API is not configured.")

    years = int(getattr(settings, "DOMAIN_REGISTRATION_YEARS", 1))
    privacy = bool(domain.privacy_enabled)
    result = client.register_domain(
        domain=domain.domain_name,
        years=max(1, years),
        contact=_contact_payload(contact),
        nameservers=_settings_nameservers() or None,
        privacy=privacy,
    )
    if not result.get("success"):
        errors = result.get("errors") or ["Unknown registrar error"]
        raise RuntimeError(f"Registrar registration failed: {'; '.join(errors)}")
    return result


def _set_namecheap_dns_hosts(domain: Domain, hosts: list[dict[str, str]]) -> None:
    if not hosts:
        return
    client = builder_domain_services.get_namecheap_client_from_settings()
    if client is None:
        raise RuntimeError("Cannot configure DNS: Namecheap API is not configured.")

    params: dict[str, str] = {"DomainName": domain.domain_name}
    for idx, host in enumerate(hosts, start=1):
        params[f"HostName{idx}"] = host["name"]
        params[f"RecordType{idx}"] = host["type"]
        params[f"Address{idx}"] = host["address"]
        params[f"TTL{idx}"] = host["ttl"]

    xml = client._call("namecheap.domains.dns.setHosts", params)  # noqa: SLF001
    try:
        root = ElementTree.fromstring(xml)
        status = root.attrib.get("Status", "").upper()
    except ElementTree.ParseError as exc:
        raise RuntimeError(f"DNS response parse failed: {exc}") from exc

    if status != "OK":
        raise RuntimeError("DNS host update failed.")


def _cert_expiry_from_pem(cert_path: Path) -> datetime:
    try:
        parsed = ssl._ssl._test_decode_cert(str(cert_path))  # type: ignore[attr-defined]
        not_after = parsed.get("notAfter")
        if not_after:
            return datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except Exception:
        logger.warning("Could not parse certificate expiry from %s", cert_path, exc_info=True)
    return datetime.now(timezone.utc) + timedelta(days=90)


def _request_letsencrypt_certificate(domain_name: str) -> tuple[str, str, datetime]:
    certbot_bin = (getattr(settings, "CERTBOT_BIN", "") or "certbot").strip()
    certbot = shutil.which(certbot_bin)
    if not certbot:
        raise RuntimeError("certbot executable was not found on PATH.")

    email = (getattr(settings, "LETSENCRYPT_EMAIL", "") or "").strip()
    if not email:
        raise RuntimeError("LETSENCRYPT_EMAIL is required for certificate requests.")

    cmd = [
        certbot,
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "--standalone",
        "-d",
        domain_name,
        "-m",
        email,
        "--keep-until-expiring",
    ]
    if bool(getattr(settings, "LETSENCRYPT_STAGING", False)):
        cmd.append("--staging")

    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "certbot failed").strip())

    live_dir = Path((getattr(settings, "LETSENCRYPT_LIVE_DIR", "") or "/etc/letsencrypt/live").strip()) / domain_name
    cert_path = live_dir / "fullchain.pem"
    key_path = live_dir / "privkey.pem"
    if not cert_path.exists() or not key_path.exists():
        raise RuntimeError(f"Certificate files not found under {live_dir}")

    cert_pem = cert_path.read_text(encoding="utf-8")
    key_pem = key_path.read_text(encoding="utf-8")
    expires_at = _cert_expiry_from_pem(cert_path)
    return cert_pem, key_pem, expires_at


def _store_ssl_certificate(domain: Domain, cert_pem: str, key_pem: str, expires_at: datetime) -> None:
    mapping, _ = DomainMapping.objects.get_or_create(
        site=domain.site,
        domain=domain.domain_name,
        defaults={
            "is_primary": domain.is_primary,
            "status": "active",
            "dns_provider": "namecheap",
            "registrar": (domain.registrar or "namecheap")[:50],
        },
    )
    if mapping.status != "active":
        mapping.status = "active"
        mapping.save(update_fields=["status", "updated_at"])

    SSLCertificate.objects.update_or_create(
        domain_mapping=mapping,
        defaults={
            "cert_file": cert_pem,
            "key_file": key_pem,
            "expires_at": expires_at,
        },
    )

    domain.ssl_enabled = True
    domain.ssl_expires_at = expires_at
    domain.save(update_fields=["ssl_enabled", "ssl_expires_at", "updated_at"])


def _schedule_ssl_renewal(domain: Domain) -> None:
    try:
        from jobs.services import create_job

        create_job(
            "renew_ssl_certificate",
            {"domain_id": domain.id, "domain_name": domain.domain_name},
            priority=5,
        )
    except Exception:
        logger.warning("Unable to enqueue SSL renewal job for %s", domain.domain_name, exc_info=True)


def check_domain_availability(domain_name: str) -> DomainAvailability:
    """Check registrar availability and persist a result row."""
    clean_domain = domain_name.strip().lower()
    details = builder_domain_services.check_availability(clean_domain)
    availability = DomainAvailability.objects.create(
        domain_name=clean_domain,
        available=bool(details.get("available")),
        price=_parse_decimal(details.get("price")),
        currency=(details.get("currency") or "USD"),
        registrar=(details.get("source") or ""),
        raw_response=details,
    )
    return availability


def check_domain_availability_details(domain_name: str) -> dict[str, Any]:
    """Return raw registrar/WHOIS availability details."""
    return builder_domain_services.check_availability(domain_name.strip().lower())


def verify_domain_ownership(domain_name: str, token: str) -> tuple[bool, str]:
    """Verify ownership via DNS TXT lookup."""
    return builder_domain_services.verify_domain_ownership(domain_name.strip().lower(), token)


def fetch_domain_whois(domain_name: str) -> dict[str, Any]:
    """Return parsed WHOIS information."""
    return builder_domain_services.whois_query(domain_name.strip().lower())


def provision_domain(domain: Domain, contact: DomainContact) -> None:
    """Register a domain, configure DNS, issue TLS, and schedule renewal."""
    was_unregistered = domain.registration_status == Domain.REG_STATUS_UNREGISTERED
    domain.last_verification_attempt = datetime.now(timezone.utc)
    domain.registration_status = Domain.REG_STATUS_PENDING_TRANSFER
    domain.save(update_fields=["last_verification_attempt", "registration_status", "updated_at"])

    try:
        if was_unregistered:
            register_result = _register_with_namecheap(domain, contact)
            domain.registrar = "namecheap"
            domain.registration_status = Domain.REG_STATUS_ACTIVE
            domain.registered_at = datetime.now(timezone.utc)
            domain.whois_data = register_result

        hosts = _build_dns_hosts(domain)
        if hosts:
            _set_namecheap_dns_hosts(domain, hosts)
            domain.dns_records = hosts
            if not domain.nameservers:
                domain.nameservers = _settings_nameservers()

        whois_data = builder_domain_services.whois_query(domain.domain_name)
        domain.whois_data = whois_data
        domain.whois_fetched_at = datetime.now(timezone.utc)
        domain.expires_at = _parse_iso_or_date(whois_data.get("expiry_date"))

        if domain.verification_token:
            ok, message = verify_domain_ownership(domain.domain_name, domain.verification_token)
            if ok:
                domain.status = Domain.STATUS_VERIFIED
                domain.verified_at = datetime.now(timezone.utc)
                domain.verification_error = ""
            else:
                domain.status = Domain.STATUS_PENDING
                domain.verification_error = message

        cert_pem, key_pem, expires_at = _request_letsencrypt_certificate(domain.domain_name)
        _store_ssl_certificate(domain, cert_pem, key_pem, expires_at)
        _schedule_ssl_renewal(domain)

        domain.registration_status = Domain.REG_STATUS_ACTIVE
        domain.save(
            update_fields=[
                "registrar",
                "registration_status",
                "registered_at",
                "whois_data",
                "whois_fetched_at",
                "expires_at",
                "dns_records",
                "nameservers",
                "status",
                "verified_at",
                "verification_error",
                "updated_at",
            ]
        )
        logger.info("Provisioned domain %s", domain.domain_name)
    except Exception as exc:
        domain.status = Domain.STATUS_FAILED
        domain.registration_status = Domain.REG_STATUS_UNREGISTERED
        domain.verification_error = str(exc)
        domain.save(update_fields=["status", "registration_status", "verification_error", "updated_at"])
        logger.exception("Failed to provision domain %s", domain.domain_name)
        raise


def ensure_domain_portfolio_entry(site, domain_name: str, verification_token: str = "") -> Domain:
    """Ensure a domain portfolio record exists for an email-hosting domain."""
    normalized = domain_name.strip().lower().rstrip(".")
    domain = Domain.objects.filter(domain_name=normalized).first()
    if domain and domain.site_id != site.id:
        raise RuntimeError("Domain already belongs to another site.")

    if domain is None:
        domain = Domain.objects.create(
            site=site,
            domain_name=normalized,
            status=Domain.STATUS_PENDING,
            verification_method=Domain.VERIFY_METHOD_DNS_TXT,
            verification_token=verification_token[:100],
            registration_status=Domain.REG_STATUS_UNREGISTERED,
        )
    else:
        changed_fields: list[str] = []
        if verification_token and domain.verification_token != verification_token[:100]:
            domain.verification_token = verification_token[:100]
            changed_fields.append("verification_token")
        if domain.status == Domain.STATUS_FAILED:
            domain.status = Domain.STATUS_PENDING
            changed_fields.append("status")
        if changed_fields:
            domain.save(update_fields=[*changed_fields, "updated_at"])

    mapping = DomainMapping.objects.filter(domain=normalized).first()
    if mapping and mapping.site_id != site.id:
        raise RuntimeError("Domain mapping already belongs to another site.")
    if mapping is None:
        DomainMapping.objects.create(
            site=site,
            domain=normalized,
            is_primary=False,
            status="pending",
            dns_provider=(domain.registrar or "")[:50],
            registrar=(domain.registrar or "")[:50],
        )
    return domain


def mark_domain_verified_for_email(site, domain_name: str) -> None:
    """Mark matching domain portfolio rows as verified after email DNS checks pass."""
    normalized = domain_name.strip().lower().rstrip(".")
    now = datetime.now(timezone.utc)
    Domain.objects.filter(site=site, domain_name=normalized).update(
        status=Domain.STATUS_VERIFIED,
        verified_at=now,
        verification_error="",
        updated_at=now,
    )
    DomainMapping.objects.filter(site=site, domain=normalized).update(status="active")


__all__ = [
    "check_domain_availability",
    "check_domain_availability_details",
    "ensure_domain_portfolio_entry",
    "fetch_domain_whois",
    "mark_domain_verified_for_email",
    "provision_domain",
    "verify_domain_ownership",
]
