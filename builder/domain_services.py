"""
Domain management services.

Uses Python stdlib only (socket, ssl, urllib, http.client) — no third-party packages.

Provides:
  - DNS TXT record lookup for domain ownership verification
  - Basic WHOIS query (port 43) with common registrar parsing
  - Namecheap API client (sandbox + production) for availability checks and registration
  - Domain portfolio helpers (expiry warnings, bulk status)
"""
from __future__ import annotations

import json
import re
import socket
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# DNS TXT verification
# ---------------------------------------------------------------------------

def lookup_dns_txt(domain: str, timeout: int = 10) -> list[str]:
    """
    Resolve TXT records for *domain* using Google's DNS-over-HTTPS API.
    Falls back to an empty list on any network error (never raises).

    Uses stdlib urllib only — no dnspython dependency.
    """
    records: list[str] = []
    try:
        url = f"https://dns.google/resolve?name={urllib.parse.quote(domain)}&type=TXT"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data: dict = json.loads(resp.read().decode())
        for answer in data.get("Answer", []):
            if answer.get("type") == 16:  # TXT record type
                # Google wraps TXT data in extra quotes — strip them
                txt = answer.get("data", "").strip('"')
                records.append(txt)
    except Exception:
        pass
    return records


def verify_domain_ownership(domain: str, token: str) -> tuple[bool, str]:
    """
    Check whether the TXT record `_webbuilder-verify.<domain>` contains *token*.
    Returns (success: bool, message: str).
    """
    fqdn = f"_webbuilder-verify.{domain}"
    try:
        records = lookup_dns_txt(fqdn)
    except Exception as exc:
        return False, f"DNS lookup error: {exc}"

    expected = f"webbuilder-verify={token}"
    for record in records:
        if record.strip() == expected:
            return True, "DNS TXT record verified."

    if records:
        return False, (
            f"TXT records found for {fqdn} but none matched. "
            f"Expected: {expected}. Found: {', '.join(records)}"
        )
    return False, (
        f"No TXT records found for {fqdn}. "
        f"Add a TXT record: name=_webbuilder-verify  value={expected}"
    )


def build_verification_instructions(domain: str, token: str) -> dict:
    """Return instructions dict that the frontend can render."""
    return {
        "method": "dns_txt",
        "record_type": "TXT",
        "record_name": f"_webbuilder-verify.{domain}",
        "record_value": f"webbuilder-verify={token}",
        "instructions": (
            "Log in to your DNS provider and add a TXT record with the name and value shown above. "
            "DNS changes can take up to 48 hours to propagate. "
            "Click 'Check Now' once the record has been added."
        ),
    }


# ---------------------------------------------------------------------------
# WHOIS lookup (RFC 3912, port 43)
# ---------------------------------------------------------------------------

WHOIS_SERVERS: dict[str, str] = {
    "com": "whois.verisign-grs.com",
    "net": "whois.verisign-grs.com",
    "org": "whois.publicinterestregistry.org",
    "io": "whois.nic.io",
    "co": "whois.nic.co",
    "uk": "whois.nic.uk",
    "de": "whois.denic.de",
    "info": "whois.afilias.net",
    "biz": "whois.neulevel.biz",
    "me": "whois.nic.me",
    "app": "whois.nic.google",
    "dev": "whois.nic.google",
    "ai": "whois.nic.ai",
    "xyz": "whois.nic.xyz",
}

_WHOIS_DATE_PATTERNS = [
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)",
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
    r"(\d{2}-\w{3}-\d{4})",
    r"(\d{4}\.\d{2}\.\d{2})",
    r"(\d{2}/\d{2}/\d{4})",
]

_WHOIS_FIELD_MAP = {
    "registrar": ["Registrar:", "registrar:"],
    "creation_date": ["Creation Date:", "Created On:", "created:", "Domain Registration Date:"],
    "expiry_date": [
        "Registry Expiry Date:", "Expiration Date:", "Registrar Registration Expiration Date:",
        "Expiry Date:", "expires:", "Domain Expiration Date:",
    ],
    "updated_date": ["Updated Date:", "Last Updated:", "last-update:"],
    "registrant_name": ["Registrant Name:", "Registrant:"],
    "registrant_email": ["Registrant Email:"],
    "name_servers": ["Name Server:", "nserver:"],
    "status": ["Domain Status:", "Status:"],
}


def _parse_date(raw: str) -> str | None:
    raw = raw.strip()
    for pattern in _WHOIS_DATE_PATTERNS:
        m = re.search(pattern, raw)
        if m:
            return m.group(1)
    return raw if raw else None


def whois_query(domain: str, timeout: int = 10) -> dict[str, Any]:
    """
    Perform a raw WHOIS query via port 43 and return a parsed dict.
    Returns empty dict on failure (never raises).
    """
    tld = domain.rsplit(".", 1)[-1].lower()
    server = WHOIS_SERVERS.get(tld, f"whois.nic.{tld}")

    try:
        sock = socket.create_connection((server, 43), timeout=timeout)
        sock.sendall(f"{domain}\r\n".encode())
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
        raw = b"".join(chunks).decode(errors="replace")
    except Exception as exc:
        return {"error": str(exc), "raw": ""}

    result: dict[str, Any] = {"raw": raw, "domain": domain}
    name_servers: list[str] = []
    statuses: list[str] = []

    for line in raw.splitlines():
        line_stripped = line.strip()
        for field, prefixes in _WHOIS_FIELD_MAP.items():
            for prefix in prefixes:
                if line_stripped.lower().startswith(prefix.lower()):
                    value = line_stripped[len(prefix):].strip()
                    if not value:
                        continue
                    if field == "name_servers":
                        name_servers.append(value.lower())
                    elif field == "status":
                        statuses.append(value.split(" ")[0])
                    elif field not in result:
                        if "date" in field:
                            result[field] = _parse_date(value)
                        else:
                            result[field] = value

    if name_servers:
        result["name_servers"] = list(dict.fromkeys(name_servers))
    if statuses:
        result["statuses"] = list(dict.fromkeys(statuses))

    result["available"] = "No match for" in raw or "NOT FOUND" in raw.upper()
    return result


# ---------------------------------------------------------------------------
# Namecheap API client (sandbox + production)
# ---------------------------------------------------------------------------

NAMECHEAP_SANDBOX_URL = "https://api.sandbox.namecheap.com/xml.response"
NAMECHEAP_PRODUCTION_URL = "https://api.namecheap.com/xml.response"


class NamecheapClient:
    """
    Thin Namecheap API client using stdlib urllib only.

    To use:
      client = NamecheapClient(api_user, api_key, username, client_ip, sandbox=True)

    Namecheap requires whitelisted client IP for API access.
    Sandbox credentials are free at https://www.sandbox.namecheap.com/
    """

    def __init__(
        self,
        api_user: str,
        api_key: str,
        username: str,
        client_ip: str,
        sandbox: bool = True,
    ) -> None:
        self.api_user = api_user
        self.api_key = api_key
        self.username = username
        self.client_ip = client_ip
        self.base_url = NAMECHEAP_SANDBOX_URL if sandbox else NAMECHEAP_PRODUCTION_URL

    def _base_params(self) -> dict:
        return {
            "ApiUser": self.api_user,
            "ApiKey": self.api_key,
            "UserName": self.username,
            "ClientIp": self.client_ip,
        }

    def _call(self, command: str, extra: dict | None = None, timeout: int = 15) -> str:
        params = {**self._base_params(), "Command": command, **(extra or {})}
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode()

    @staticmethod
    def _parse_xml_value(xml: str, tag: str) -> str:
        m = re.search(rf"<{tag}[^>]*>([^<]*)</{tag}>", xml, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _parse_xml_attrs(xml: str, tag: str) -> list[dict]:
        """Return list of attribute dicts for all occurrences of *tag*."""
        results = []
        for m in re.finditer(rf"<{tag}\s([^>]+)/>", xml, re.IGNORECASE):
            attr_str = m.group(1)
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', attr_str))
            results.append(attrs)
        return results

    def check_availability(self, domain_list: list[str]) -> list[dict]:
        """
        Check availability for up to 50 domains.
        Returns list of {domain, available, premium, price}.
        """
        domains_str = ",".join(domain_list[:50])
        xml = self._call("namecheap.domains.check", {"DomainList": domains_str})
        results = []
        for attrs in self._parse_xml_attrs(xml, "DomainCheckResult"):
            results.append({
                "domain": attrs.get("Domain", ""),
                "available": attrs.get("Available", "false").lower() == "true",
                "premium": attrs.get("IsPremiumName", "false").lower() == "true",
                "price": attrs.get("PremiumRegistrationPrice", ""),
                "error_no": attrs.get("ErrorNo", "0"),
                "description": attrs.get("Description", ""),
            })
        return results

    def get_tld_pricing(self, tld: str = "com") -> dict:
        """Get registration pricing for a TLD."""
        xml = self._call(
            "namecheap.users.getPricing",
            {"ProductType": "DOMAIN", "ProductCategory": "REGISTER", "ProductName": tld},
        )
        price_info: dict = {}
        for attrs in self._parse_xml_attrs(xml, "Price"):
            price_info[attrs.get("Duration", "1")] = {
                "regular_price": attrs.get("RegularPrice", ""),
                "your_price": attrs.get("YourPrice", ""),
                "currency": attrs.get("Currency", "USD"),
            }
        return price_info

    def register_domain(
        self,
        domain: str,
        years: int,
        contact: dict,
        nameservers: list[str] | None = None,
        privacy: bool = False,
    ) -> dict:
        """
        Register a domain.

        contact dict keys (all required unless marked optional):
          first_name, last_name, email, phone (format: +CountryCode.Number),
          organization (optional), address1, city, state, postal_code, country (2-letter ISO)
        """
        sld, tld = domain.rsplit(".", 1)
        params: dict = {
            "DomainName": domain,
            "Years": str(years),
            "RegistrantFirstName": contact["first_name"],
            "RegistrantLastName": contact["last_name"],
            "RegistrantAddress1": contact["address1"],
            "RegistrantCity": contact["city"],
            "RegistrantStateProvince": contact["state"],
            "RegistrantPostalCode": contact["postal_code"],
            "RegistrantCountry": contact["country"],
            "RegistrantPhone": contact["phone"],
            "RegistrantEmailAddress": contact["email"],
            "RegistrantOrganizationName": contact.get("organization", ""),
            # Mirror to Tech/Admin/Billing contacts
            "TechFirstName": contact["first_name"],
            "TechLastName": contact["last_name"],
            "TechAddress1": contact["address1"],
            "TechCity": contact["city"],
            "TechStateProvince": contact["state"],
            "TechPostalCode": contact["postal_code"],
            "TechCountry": contact["country"],
            "TechPhone": contact["phone"],
            "TechEmailAddress": contact["email"],
            "AdminFirstName": contact["first_name"],
            "AdminLastName": contact["last_name"],
            "AdminAddress1": contact["address1"],
            "AdminCity": contact["city"],
            "AdminStateProvince": contact["state"],
            "AdminPostalCode": contact["postal_code"],
            "AdminCountry": contact["country"],
            "AdminPhone": contact["phone"],
            "AdminEmailAddress": contact["email"],
            "AuxBillingFirstName": contact["first_name"],
            "AuxBillingLastName": contact["last_name"],
            "AuxBillingAddress1": contact["address1"],
            "AuxBillingCity": contact["city"],
            "AuxBillingStateProvince": contact["state"],
            "AuxBillingPostalCode": contact["postal_code"],
            "AuxBillingCountry": contact["country"],
            "AuxBillingPhone": contact["phone"],
            "AuxBillingEmailAddress": contact["email"],
            "AddFreeWhoisguard": "yes" if privacy else "no",
            "WGEnabled": "yes" if privacy else "no",
        }
        if nameservers:
            for i, ns in enumerate(nameservers[:5], start=1):
                params[f"Nameservers"] = ",".join(nameservers[:5])

        xml = self._call("namecheap.domains.create", params)

        status = self._parse_xml_value(xml, "Status")
        domain_id = self._parse_xml_value(xml, "DomainID")
        registered = self._parse_xml_value(xml, "Registered")
        errors = re.findall(r'<Error Number="\d+"[^>]*>([^<]+)</Error>', xml)

        return {
            "success": registered.lower() == "true" or status.lower() == "ok",
            "domain_id": domain_id,
            "domain": domain,
            "registered": registered,
            "status": status,
            "errors": errors,
            "raw_xml": xml,
        }

    def get_domain_info(self, domain: str) -> dict:
        """Retrieve domain info from Namecheap account."""
        sld, tld = domain.rsplit(".", 1)
        xml = self._call("namecheap.domains.getInfo", {"DomainName": domain})
        return {
            "domain": domain,
            "status": self._parse_xml_value(xml, "Status"),
            "created": self._parse_xml_value(xml, "Created"),
            "expires": self._parse_xml_value(xml, "Expires"),
            "is_locked": self._parse_xml_value(xml, "IsLocked"),
            "auto_renew": self._parse_xml_value(xml, "AutoRenew"),
            "whoisguard": self._parse_xml_value(xml, "WhoisGuard"),
            "raw_xml": xml,
        }

    def list_domains(self, page: int = 1, page_size: int = 100) -> dict:
        """List all domains in the Namecheap account."""
        xml = self._call(
            "namecheap.domains.getList",
            {"Page": str(page), "PageSize": str(page_size)},
        )
        domains = []
        for attrs in self._parse_xml_attrs(xml, "Domain"):
            domains.append({
                "name": attrs.get("Name", ""),
                "created": attrs.get("Created", ""),
                "expires": attrs.get("Expires", ""),
                "is_expired": attrs.get("IsExpired", "false").lower() == "true",
                "is_locked": attrs.get("IsLocked", "false").lower() == "true",
                "auto_renew": attrs.get("AutoRenew", "false").lower() == "true",
                "whoisguard": attrs.get("WhoisGuard", ""),
            })
        total_items = self._parse_xml_value(xml, "TotalItems")
        return {
            "domains": domains,
            "total": int(total_items) if total_items.isdigit() else len(domains),
            "page": page,
            "page_size": page_size,
        }


# ---------------------------------------------------------------------------
# Registrar config resolver
# ---------------------------------------------------------------------------

def get_namecheap_client_from_settings() -> NamecheapClient | None:
    """
    Build a NamecheapClient from Django settings, returning None if unconfigured.

    Expected settings (in config/settings.py or env vars):
      NAMECHEAP_API_USER, NAMECHEAP_API_KEY, NAMECHEAP_USERNAME,
      NAMECHEAP_CLIENT_IP, NAMECHEAP_SANDBOX (default True)
    """
    try:
        from django.conf import settings
        import os
        api_user = getattr(settings, "NAMECHEAP_API_USER", None) or os.environ.get("NAMECHEAP_API_USER", "")
        api_key = getattr(settings, "NAMECHEAP_API_KEY", None) or os.environ.get("NAMECHEAP_API_KEY", "")
        username = getattr(settings, "NAMECHEAP_USERNAME", None) or os.environ.get("NAMECHEAP_USERNAME", "")
        client_ip = getattr(settings, "NAMECHEAP_CLIENT_IP", None) or os.environ.get("NAMECHEAP_CLIENT_IP", "")
        sandbox_val = getattr(settings, "NAMECHEAP_SANDBOX", None)
        if sandbox_val is None:
            sandbox_val = os.environ.get("NAMECHEAP_SANDBOX", "true")
        sandbox = str(sandbox_val).lower() in {"1", "true", "yes"}
        if not all([api_user, api_key, username, client_ip]):
            return None
        return NamecheapClient(api_user, api_key, username, client_ip, sandbox=sandbox)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public-facing domain availability check (no registrar required)
# ---------------------------------------------------------------------------

def check_availability_via_whois(domain: str) -> dict:
    """
    Check domain availability using WHOIS. No registrar credentials required.
    Returns {domain, available, whois_data, checked_at}.
    """
    data = whois_query(domain)
    available = data.get("available", False)
    return {
        "domain": domain,
        "available": available,
        "whois_data": data,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "whois",
    }


def check_availability(domain: str) -> dict:
    """
    Check availability: tries Namecheap API first; falls back to WHOIS.
    Always returns {domain, available, price, currency, source, checked_at}.
    """
    client = get_namecheap_client_from_settings()
    if client:
        try:
            results = client.check_availability([domain])
            if results:
                r = results[0]
                return {
                    "domain": domain,
                    "available": r["available"],
                    "premium": r.get("premium", False),
                    "price": r.get("price") or None,
                    "currency": "USD",
                    "source": "namecheap",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "errors": r.get("errors", []),
                }
        except Exception:
            pass

    return check_availability_via_whois(domain)


# ---------------------------------------------------------------------------
# Domain expiry helpers
# ---------------------------------------------------------------------------

def days_until_expiry(expires_at_str: str | None) -> int | None:
    """Return days until expiry from an ISO datetime string, or None if unparseable."""
    if not expires_at_str:
        return None
    try:
        from django.utils.dateparse import parse_datetime
        dt = parse_datetime(expires_at_str)
        if dt is None:
            return None
        now = datetime.now(timezone.utc)
        delta = dt - now
        return delta.days
    except Exception:
        return None


def get_expiry_status(days: int | None) -> str:
    """Return a UI-friendly expiry status label."""
    if days is None:
        return "unknown"
    if days < 0:
        return "expired"
    if days <= 14:
        return "critical"
    if days <= 30:
        return "warning"
    if days <= 90:
        return "notice"
    return "ok"
