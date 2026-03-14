"""
SEO service layer.

- run_page_audit(page, request)  → performs a real HTTP crawl of the published
  page URL and stores an SEOAudit record.
- gsc_build_auth_url(site, request) → returns the Google OAuth2 consent URL.
- gsc_exchange_code(site, code, state, request) → exchanges the auth code for
  tokens and stores them.
- gsc_sync(site, request) → fetches GSC search analytics and upserts SEOAnalytics.
- gsc_disconnect(site) → removes stored credentials.

All GSC functions are no-ops (returning a helpful error) when the required
environment variables are not configured, so the app boots cleanly without
a GCP project.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any

from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env config
# ---------------------------------------------------------------------------

GSC_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GSC_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GSC_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/seo/gsc/callback/"
)
_GSC_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GSC_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GSC_SCOPES = "https://www.googleapis.com/auth/webmasters.readonly"
_GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
_GSC_STATE_SALT = "builder.gsc.state"
_GSC_TOKEN_PREFIX = "enc:"
_GSC_TOKEN_VERSION = "v1"
_GSC_TOKEN_NONCE_BYTES = 16
_GSC_TOKEN_MAC_BYTES = 32


def _gsc_configured() -> bool:
    return bool(GSC_CLIENT_ID and GSC_CLIENT_SECRET)


def _gsc_secret_keys() -> tuple[bytes, bytes]:
    secret_material = settings.SECRET_KEY or GSC_CLIENT_SECRET
    if not secret_material:
        raise RuntimeError("Missing secret key material for GSC credential encryption.")
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret_material.encode(),
        b"builder.gsc.tokens",
        390000,
        dklen=64,
    )
    return derived[:32], derived[32:]


def _xor_keystream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < len(data):
        block = hmac.new(
            key,
            nonce + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        chunks.append(block)
        counter += 1
    stream = b"".join(chunks)[: len(data)]
    return bytes(left ^ right for left, right in zip(data, stream))


def _encrypt_gsc_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_GSC_TOKEN_PREFIX):
        return value
    encryption_key, auth_key = _gsc_secret_keys()
    nonce = secrets.token_bytes(_GSC_TOKEN_NONCE_BYTES)
    ciphertext = _xor_keystream(value.encode(), encryption_key, nonce)
    mac = hmac.new(auth_key, nonce + ciphertext, hashlib.sha256).digest()
    payload = base64.urlsafe_b64encode(nonce + ciphertext + mac).decode("ascii")
    return f"{_GSC_TOKEN_PREFIX}{_GSC_TOKEN_VERSION}:{payload}"


def _decrypt_gsc_secret(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(_GSC_TOKEN_PREFIX):
        return value
    try:
        version, encoded = value[len(_GSC_TOKEN_PREFIX):].split(":", 1)
        if version != _GSC_TOKEN_VERSION:
            logger.warning("Unsupported stored GSC token version: %s", version)
            return ""
        raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, binascii.Error):
        logger.warning("Unable to decode stored GSC token.")
        return ""

    minimum_length = _GSC_TOKEN_NONCE_BYTES + _GSC_TOKEN_MAC_BYTES
    if len(raw) < minimum_length:
        logger.warning("Stored GSC token payload is too short.")
        return ""

    nonce = raw[:_GSC_TOKEN_NONCE_BYTES]
    ciphertext = raw[_GSC_TOKEN_NONCE_BYTES:-_GSC_TOKEN_MAC_BYTES]
    mac = raw[-_GSC_TOKEN_MAC_BYTES:]
    encryption_key, auth_key = _gsc_secret_keys()
    expected_mac = hmac.new(auth_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        logger.warning("Unable to decrypt stored GSC token.")
        return ""
    return _xor_keystream(ciphertext, encryption_key, nonce).decode()


def gsc_parse_state(state: str, *, max_age_seconds: int = 600) -> dict[str, int]:
    payload = signing.loads(state, salt=_GSC_STATE_SALT, max_age=max_age_seconds)
    return {
        "site_id": int(payload["site_id"]),
        "user_id": int(payload["user_id"]),
    }


# ---------------------------------------------------------------------------
# Page audit
# ---------------------------------------------------------------------------

def _fetch_url(url: str, timeout: int = 10) -> tuple[int, str, int]:
    """Returns (status_code, body_text, response_time_ms)."""
    headers = {
        "User-Agent": (
            "WebsiteBuilderBot/1.0 (SEO audit; +https://github.com/builder)"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            elapsed = int((time.monotonic() - t0) * 1000)
            return resp.status, body, elapsed
    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body, elapsed
    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        raise RuntimeError(str(exc)) from exc


def _extract_meta(body: str, name: str) -> str:
    patterns = [
        rf'<meta\s[^>]*name=["\'](?i){re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
        rf'<meta\s[^>]*content=["\']([^"\']*)["\'][^>]*name=["\'](?i){re.escape(name)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            return html.unescape(m.group(1).strip())
    return ""


def _extract_og(body: str, prop: str) -> str:
    patterns = [
        rf'<meta\s[^>]*property=["\']og:{re.escape(prop)}["\'][^>]*content=["\']([^"\']*)["\']',
        rf'<meta\s[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:{re.escape(prop)}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, body, re.IGNORECASE)
        if m:
            return html.unescape(m.group(1).strip())
    return ""


def _count_words(body: str) -> int:
    text = re.sub(r"<[^>]+>", " ", body)
    text = html.unescape(text)
    return len(text.split())


def _score_audit(audit_data: dict) -> tuple[int, list[dict]]:
    """Returns (0-100 score, issues list)."""
    score = 100
    issues: list[dict] = []

    def deduct(points: int, severity: str, message: str, tip: str = "") -> None:
        nonlocal score
        score -= points
        issues.append({"severity": severity, "message": message, "tip": tip})

    title_len = audit_data.get("title_length", 0)
    if title_len == 0:
        deduct(15, "critical", "Page title is missing", "Add a <title> tag.")
    elif title_len < 30:
        deduct(8, "warning", f"Title is too short ({title_len} chars)", "Aim for 50–60 characters.")
    elif title_len > 60:
        deduct(5, "warning", f"Title may be truncated ({title_len} chars)", "Keep titles under 60 characters.")

    desc_len = audit_data.get("meta_description_length", 0)
    if desc_len == 0:
        deduct(10, "critical", "Meta description is missing", "Add a <meta name='description'> tag.")
    elif desc_len < 70:
        deduct(5, "warning", f"Meta description is too short ({desc_len} chars)", "Aim for 120–160 characters.")
    elif desc_len > 160:
        deduct(3, "warning", f"Meta description is too long ({desc_len} chars)", "Keep it under 160 characters.")

    h1_count = audit_data.get("h1_count", 0)
    if h1_count == 0:
        deduct(10, "critical", "No H1 heading found", "Add a single H1 tag per page.")
    elif h1_count > 1:
        deduct(5, "warning", f"Multiple H1 tags found ({h1_count})", "Use only one H1 per page.")

    if not audit_data.get("canonical_url"):
        deduct(5, "info", "No canonical URL tag found", "Add <link rel='canonical' href='...'> to avoid duplicate content.")

    if not audit_data.get("og_title"):
        deduct(5, "info", "Missing Open Graph title (og:title)", "Add Open Graph tags for better social sharing.")

    if audit_data.get("images_missing_alt", 0) > 0:
        n = audit_data["images_missing_alt"]
        deduct(min(n * 2, 10), "warning", f"{n} image(s) missing alt text", "Add descriptive alt attributes to all images.")

    resp_ms = audit_data.get("response_time_ms", 0)
    if resp_ms > 3000:
        deduct(10, "critical", f"Slow page load ({resp_ms}ms)", "Aim for < 1 second.")
    elif resp_ms > 1500:
        deduct(5, "warning", f"Page load is slow ({resp_ms}ms)", "Aim for < 1 second.")

    if not audit_data.get("has_schema_markup"):
        deduct(3, "info", "No structured data (Schema.org) detected", "Add JSON-LD schema to improve rich results.")

    score = max(0, score)
    return score, issues


def run_page_audit(page: Any, base_url: str) -> Any:
    """
    Crawl the page's published URL and store an SEOAudit.
    `base_url` should be the scheme+host e.g. 'http://127.0.0.1:8000'.
    Returns the saved SEOAudit instance.
    """
    from .models import SEOAudit

    audit = SEOAudit.objects.create(
        site=page.site,
        page=page,
        audited_url="",
        status=SEOAudit.STATUS_RUNNING,
    )

    try:
        url = f"{base_url}/preview/{page.site.slug}{page.path}"
        audit.audited_url = url
        audit.save(update_fields=["audited_url", "status"])

        status_code, body, resp_ms = _fetch_url(url)
        audit.status_code = status_code
        audit.response_time_ms = resp_ms

        if status_code >= 400:
            audit.status = SEOAudit.STATUS_ERROR
            audit.error_message = f"HTTP {status_code}"
            audit.save()
            return audit

        # Title
        m = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        title = html.unescape(m.group(1).strip()) if m else ""
        audit.title = title[:500]
        audit.title_length = len(title)

        # Meta description
        desc = _extract_meta(body, "description")
        audit.meta_description = desc[:1000]
        audit.meta_description_length = len(desc)

        # H1
        h1s = re.findall(r"<h1[^>]*>(.*?)</h1>", body, re.IGNORECASE | re.DOTALL)
        h1s_clean = [re.sub(r"<[^>]+>", "", h).strip() for h in h1s]
        audit.h1_count = len(h1s_clean)
        audit.h1_text = " | ".join(h1s_clean)[:500]

        # Canonical
        m_can = re.search(
            r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
            body, re.IGNORECASE
        )
        audit.canonical_url = (m_can.group(1) if m_can else "")[:1000]

        # Open Graph
        audit.og_title = _extract_og(body, "title")[:500]
        audit.og_description = _extract_og(body, "description")[:1000]
        audit.og_image = _extract_og(body, "image")[:1000]

        # Images
        imgs = re.findall(r"<img\b([^>]*)>", body, re.IGNORECASE)
        audit.image_count = len(imgs)
        audit.images_missing_alt = sum(
            1 for attr in imgs
            if not re.search(r'\balt=["\'][^"\']+["\']', attr, re.IGNORECASE)
        )

        # Word count
        audit.word_count = _count_words(body)

        # Links
        all_links = re.findall(r'<a\b[^>]*href=["\']([^"\']*)["\']', body, re.IGNORECASE)
        parsed_base = urllib.parse.urlparse(url)
        internal = external = 0
        for link in all_links:
            if not link or link.startswith("#") or link.startswith("mailto:"):
                continue
            parsed = urllib.parse.urlparse(link)
            if parsed.netloc and parsed.netloc != parsed_base.netloc:
                external += 1
            else:
                internal += 1
        audit.internal_links = internal
        audit.external_links = external

        # Schema markup
        audit.has_schema_markup = bool(
            re.search(r'application/ld\+json', body, re.IGNORECASE)
        )

        # Score
        data = {
            "title_length": audit.title_length,
            "meta_description_length": audit.meta_description_length,
            "h1_count": audit.h1_count,
            "canonical_url": audit.canonical_url,
            "og_title": audit.og_title,
            "images_missing_alt": audit.images_missing_alt,
            "response_time_ms": audit.response_time_ms,
            "has_schema_markup": audit.has_schema_markup,
        }
        score, issues = _score_audit(data)
        audit.score = score
        audit.issues = issues
        audit.status = SEOAudit.STATUS_DONE

    except Exception as exc:
        logger.exception("SEO audit failed for page %s", page.id)
        audit.status = SEOAudit.STATUS_ERROR
        audit.error_message = str(exc)[:500]

    audit.save()
    return audit


# ---------------------------------------------------------------------------
# Google Search Console OAuth
# ---------------------------------------------------------------------------

def gsc_build_auth_url(site_id: int, user_id: int, redirect_uri: str | None = None) -> dict:
    if not _gsc_configured():
        return {
            "error": (
                "Google Search Console is not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables."
            )
        }
    redirect = redirect_uri or GSC_REDIRECT_URI
    state = signing.dumps(
        {"site_id": int(site_id), "user_id": int(user_id)},
        salt=_GSC_STATE_SALT,
    )
    params = {
        "client_id": GSC_CLIENT_ID,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": _GSC_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = f"{_GSC_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return {"auth_url": url, "state": state}


def gsc_exchange_code(site_id: int, code: str, redirect_uri: str | None = None) -> dict:
    from django.utils import timezone
    from .models import SearchConsoleCredential, Site

    if not _gsc_configured():
        return {"error": "Google client credentials not configured."}

    redirect = redirect_uri or GSC_REDIRECT_URI
    payload = {
        "code": code,
        "client_id": GSC_CLIENT_ID,
        "client_secret": GSC_CLIENT_SECRET,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        _GSC_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()
        return {"error": f"Token exchange failed: {err_body}"}
    except Exception as exc:
        return {"error": str(exc)}

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    expiry = timezone.now() + timedelta(seconds=expires_in)

    try:
        site = Site.objects.get(pk=site_id)
    except Site.DoesNotExist:
        return {"error": "Site not found."}

    cred, _ = SearchConsoleCredential.objects.get_or_create(site=site)
    cred.access_token = _encrypt_gsc_secret(access_token)
    if refresh_token:
        cred.refresh_token = _encrypt_gsc_secret(refresh_token)
    cred.token_expiry = expiry
    cred.scopes = [_GSC_SCOPES]
    cred.sync_error = ""
    cred.save()
    return {"ok": True, "site": site_id}


def _gsc_refresh_token(cred: Any) -> bool:
    """Refresh access token using refresh_token. Returns True on success."""
    from django.utils import timezone

    refresh_token = _decrypt_gsc_secret(cred.refresh_token)
    if not refresh_token:
        return False
    payload = {
        "client_id": GSC_CLIENT_ID,
        "client_secret": GSC_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        _GSC_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode())
    except Exception:
        return False

    refreshed_access_token = token_data.get("access_token", "")
    if refreshed_access_token:
        cred.access_token = _encrypt_gsc_secret(refreshed_access_token)
    expires_in = token_data.get("expires_in", 3600)
    cred.token_expiry = timezone.now() + timedelta(seconds=expires_in)
    cred.save(update_fields=["access_token", "token_expiry", "updated_at"])
    return True


def _gsc_request(cred: Any, endpoint: str, payload: dict) -> dict | list | None:
    """POST to GSC API, refreshing token if needed."""
    from django.utils import timezone

    if cred.token_expiry and cred.token_expiry <= timezone.now():
        if not _gsc_refresh_token(cred):
            raise RuntimeError("Could not refresh GSC access token.")

    access_token = _decrypt_gsc_secret(cred.access_token)
    if not access_token:
        raise RuntimeError("Stored GSC access token is unavailable.")

    url = f"{_GSC_API_BASE}/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def gsc_sync(site: Any, days: int = 90) -> dict:
    """
    Fetch search analytics from GSC and upsert into SEOAnalytics.
    Returns summary dict.
    """
    from django.utils import timezone
    from .models import SEOAnalytics, SearchConsoleCredential

    try:
        cred = site.gsc_credential
    except SearchConsoleCredential.DoesNotExist:
        return {"error": "No GSC credentials found for this site."}

    if not _decrypt_gsc_secret(cred.access_token):
        return {"error": "GSC not connected."}

    if not cred.property_url:
        return {"error": "GSC property URL not set. Update it via SEO settings."}

    end_date = date.today() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)

    property_url = cred.property_url
    enc = urllib.parse.quote(property_url, safe="")

    rows_upserted = 0
    errors: list[str] = []

    for dimension in [("page",), ("query",)]:
        payload = {
            "startDate": str(start_date),
            "endDate": str(end_date),
            "dimensions": list(dimension),
            "rowLimit": 1000,
        }
        try:
            result = _gsc_request(
                cred,
                f"sites/{enc}/searchAnalytics/query",
                payload,
            )
        except Exception as exc:
            err_msg = str(exc)
            errors.append(err_msg)
            cred.sync_error = err_msg[:500]
            cred.save(update_fields=["sync_error", "updated_at"])
            continue

        if not result or "rows" not in result:
            continue

        for row in result["rows"]:
            keys = row.get("keys", [])
            page_url = keys[0] if dimension == ("page",) else ""
            query = keys[0] if dimension == ("query",) else ""

            row_date_str = row.get("date", str(end_date))
            try:
                row_date = date.fromisoformat(row_date_str)
            except Exception:
                row_date = end_date

            # Try to match page by path
            page_obj = None
            if page_url:
                parsed = urllib.parse.urlparse(page_url)
                path = parsed.path.rstrip("/") + "/"
                page_obj = site.pages.filter(path=path).first()

            defaults = {
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "ctr": float(row.get("ctr", 0.0)),
                "average_position": float(row.get("position", 0.0)),
                "metadata": {"query": query, "url": page_url} if query else {"url": page_url},
            }

            obj, created = SEOAnalytics.objects.update_or_create(
                site=site,
                page=page_obj,
                date=row_date,
                source="google_search_console",
                defaults=defaults,
            )
            rows_upserted += 1

    cred.last_synced_at = timezone.now()
    cred.sync_error = "; ".join(errors) if errors else ""
    cred.save(update_fields=["last_synced_at", "sync_error", "updated_at"])

    return {
        "rows_upserted": rows_upserted,
        "errors": errors,
        "synced_at": str(cred.last_synced_at),
    }


def gsc_disconnect(site: Any) -> None:
    from .models import SearchConsoleCredential
    try:
        cred = site.gsc_credential
        cred.access_token = ""
        cred.refresh_token = ""
        cred.token_expiry = None
        cred.save()
    except SearchConsoleCredential.DoesNotExist:
        pass


def gsc_list_properties(site: Any) -> list[str]:
    """List GSC properties accessible with the stored token."""
    from .models import SearchConsoleCredential

    try:
        cred = site.gsc_credential
    except SearchConsoleCredential.DoesNotExist:
        return []

    access_token = _decrypt_gsc_secret(cred.access_token)
    if not access_token:
        return []

    url = f"{_GSC_API_BASE}/sites"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return [s.get("siteUrl", "") for s in data.get("siteEntry", [])]
    except Exception:
        return []
