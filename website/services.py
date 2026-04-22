from __future__ import annotations

import secrets
from typing import Any

from django.utils import timezone

from blog.models import Post
from cms.models import Page, PublishSnapshot
from cms.services import public_robots_payload, public_sitemap_entries
from commerce.models import Product
from core.models import Site
from domains.models import Domain, SSLCertificateProvisioning
from domains.services import verify_domain_ownership
from shared.contracts.sanitize import sanitize_json_payload, sanitize_text
from shared.seo import normalize_seo_payload


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def website_settings_for_site(site: Site) -> dict[str, Any]:
    settings = _safe_dict(site.settings)
    seo_defaults = normalize_seo_payload(_safe_dict(settings.get("seo")))
    return {
        "site": site.id,
        "seo_defaults": seo_defaults,
        "branding": _safe_dict(settings.get("branding")),
        "localization": _safe_dict(settings.get("localization")),
        "deployment": _safe_dict(settings.get("deployment")),
        "robots": _safe_dict(settings.get("robots")),
        "cookie_consent": _safe_dict(settings.get("cookie_consent")),
        "runtime": _safe_dict(settings.get("runtime")),
    }


def update_website_settings(site: Site, payload: dict[str, Any]) -> dict[str, Any]:
    settings = _safe_dict(site.settings)
    for key in ("seo_defaults", "branding", "localization", "deployment", "robots", "cookie_consent", "runtime"):
        if key not in payload:
            continue
        target_key = "seo" if key == "seo_defaults" else key
        sanitized = sanitize_json_payload(payload.get(key), max_depth=8)
        if target_key == "seo":
            sanitized = normalize_seo_payload(sanitized)
        settings[target_key] = sanitized
    site.settings = settings
    site.save(update_fields=["settings", "updated_at"])
    return website_settings_for_site(site)


def website_domain_records(site: Site) -> list[dict[str, Any]]:
    domains = Domain.objects.filter(site=site).order_by("-is_primary", "domain_name")
    return [
        {
            "id": domain.id,
            "domain_name": domain.domain_name,
            "status": domain.status,
            "verification_state": domain.verification_state,
            "is_primary": domain.is_primary,
            "verification_method": domain.verification_method,
            "verified_at": domain.verified_at,
            "verification_error": domain.verification_error or "",
            "ssl_status": domain.ssl_status,
            "ssl_expires_at": domain.ssl_expires_at,
            "nameservers": domain.nameservers if isinstance(domain.nameservers, list) else [],
            "dns_records": domain.dns_records if isinstance(domain.dns_records, dict) else {},
        }
        for domain in domains
    ]


def verify_site_domain(domain: Domain, *, check_now: bool = True) -> dict[str, Any]:
    if not domain.verification_token:
        domain.verification_token = secrets.token_hex(24)
        domain.verification_state = Domain.STATUS_REQUESTED
        domain.save(update_fields=["verification_token", "verification_state", "updated_at"])
    if check_now:
        domain.verification_state = Domain.STATUS_VERIFYING
        domain.save(update_fields=["verification_state", "updated_at"])
        ok, message = verify_domain_ownership(domain.domain_name, domain.verification_token)
        domain.last_verification_attempt = timezone.now()
        if ok:
            domain.status = Domain.STATUS_VERIFIED
            domain.verification_state = Domain.STATUS_VERIFIED
            domain.verified_at = timezone.now()
            domain.verification_error = ""
        else:
            domain.status = Domain.STATUS_FAILED
            domain.verification_state = Domain.STATUS_FAILED
            domain.verification_error = sanitize_text(message, max_length=500)
        domain.save(
            update_fields=[
                "status",
                "verification_state",
                "verified_at",
                "verification_error",
                "last_verification_attempt",
                "updated_at",
            ]
        )
    return {
        "domain_id": domain.id,
        "domain_name": domain.domain_name,
        "verification_token": domain.verification_token,
        "status": domain.status,
        "verification_state": domain.verification_state,
        "verification_error": domain.verification_error or "",
        "verified_at": domain.verified_at,
    }


def website_publish_status(site: Site) -> dict[str, Any]:
    last_publish = (
        PublishSnapshot.objects.filter(site=site)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    settings = _safe_dict(site.settings)
    publish_history = list(
        PublishSnapshot.objects.filter(site=site)
        .order_by("-created_at")
        .values("id", "target_type", "target_id", "revision_label", "metadata", "created_at")[:20]
    )
    return {
        "site": site.id,
        "pages_published": site.pages.filter(status=Page.STATUS_PUBLISHED).count(),
        "posts_published": site.posts.filter(status=Post.STATUS_PUBLISHED).count(),
        "products_published": site.products.filter(status=Product.STATUS_PUBLISHED).count(),
        "last_publish_at": last_publish,
        "publish_history": publish_history,
        "deployment": _safe_dict(settings.get("deployment")),
    }


def update_deployment_metadata(site: Site, deployment_payload: dict[str, Any]) -> dict[str, Any]:
    settings = _safe_dict(site.settings)
    deployment = _safe_dict(settings.get("deployment"))
    deployment.update(sanitize_json_payload(deployment_payload, max_depth=6))
    deployment["updated_at"] = timezone.now().isoformat()
    settings["deployment"] = deployment
    site.settings = settings
    site.save(update_fields=["settings", "updated_at"])
    return website_publish_status(site)


def request_ssl_provisioning(domain: Domain, *, provider: str = "internal") -> dict[str, Any]:
    provisioning = SSLCertificateProvisioning.objects.create(
        domain=domain,
        provider=(provider or "internal")[:80],
        status=SSLCertificateProvisioning.STATUS_PENDING,
        metadata={"source": "website.api"},
    )
    domain.ssl_status = "pending"
    domain.save(update_fields=["ssl_status", "updated_at"])
    return {
        "domain_id": domain.id,
        "domain_name": domain.domain_name,
        "ssl_status": domain.ssl_status,
        "provisioning_id": provisioning.id,
    }


def website_robots(site: Site, *, scheme: str, host: str) -> dict[str, Any]:
    sitemap_url = f"{scheme}://{host}/sitemap.xml" if host else f"{scheme}://example.invalid/sitemap.xml"
    return public_robots_payload(site, sitemap_url=sitemap_url)


def website_sitemap(site: Site) -> list[dict[str, Any]]:
    return public_sitemap_entries(site)
