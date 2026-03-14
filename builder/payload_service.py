from __future__ import annotations

import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings


PAYLOAD_LICENSE = "MIT"
PAYLOAD_SOURCE_URL = "https://github.com/payloadcms/payload"
PAYLOAD_CMS_SOURCE_URL = "https://github.com/payloadcms/payload/tree/main/templates/website"
PAYLOAD_ECOMMERCE_SOURCE_URL = "https://github.com/payloadcms/payload/tree/main/templates/ecommerce"


def payload_root() -> Path:
    return settings.BASE_DIR.parent / "vendor" / "payload"


def payload_license_path() -> Path:
    return payload_root() / "LICENSE.md"


def payload_package_json() -> Path:
    return payload_root() / "package.json"


def payload_template_root(template_name: str) -> Path:
    return payload_root() / "templates" / template_name


def payload_template_package_json(template_name: str) -> Path:
    return payload_template_root(template_name) / "package.json"


def payload_source_exists() -> bool:
    return payload_package_json().exists() and payload_license_path().exists()


def payload_template_exists(template_name: str) -> bool:
    return payload_source_exists() and payload_template_package_json(template_name).exists()


def payload_cms_source_exists() -> bool:
    return payload_template_exists("website")


def payload_ecommerce_source_exists() -> bool:
    return payload_template_exists("ecommerce")


def payload_dependencies_ready() -> bool:
    return (payload_root() / "node_modules").exists()


def payload_install_command() -> str:
    return "pnpm install"


def payload_node_binary() -> str:
    return shutil.which("pnpm.cmd") or shutil.which("pnpm") or "pnpm.cmd"


def payload_cms_launch_command() -> str:
    return "python manage.py run_payload_cms"


def payload_ecommerce_launch_command() -> str:
    return "python manage.py run_payload_ecommerce"


def payload_cms_public_url() -> str:
    configured = (settings.PAYLOAD_CMS_PUBLIC_URL or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://{settings.PAYLOAD_CMS_HOST}:{settings.PAYLOAD_CMS_PORT}"


def payload_ecommerce_public_url() -> str:
    configured = (settings.PAYLOAD_ECOMMERCE_PUBLIC_URL or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://{settings.PAYLOAD_ECOMMERCE_HOST}:{settings.PAYLOAD_ECOMMERCE_PORT}"


def payload_cms_database_configured() -> bool:
    return bool((settings.PAYLOAD_CMS_DATABASE_URL or "").strip())


def payload_cms_secret_configured() -> bool:
    return bool((settings.PAYLOAD_CMS_SECRET or "").strip())


def payload_ecommerce_database_configured() -> bool:
    return bool((settings.PAYLOAD_ECOMMERCE_DATABASE_URL or "").strip())


def payload_ecommerce_secret_configured() -> bool:
    return bool((settings.PAYLOAD_ECOMMERCE_SECRET or "").strip())


def payload_ecommerce_stripe_configured() -> bool:
    return all(
        (
            settings.PAYLOAD_ECOMMERCE_STRIPE_SECRET_KEY,
            settings.PAYLOAD_ECOMMERCE_STRIPE_PUBLISHABLE_KEY,
            settings.PAYLOAD_ECOMMERCE_STRIPE_WEBHOOK_SECRET,
        )
    )


def _probe_tcp(host: str, port: int, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http(public_url: str, host: str, port: int, timeout: float = 1.5) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(public_url)
    target_host = parsed.hostname or host
    target_port = parsed.port or port
    tcp_open = _probe_tcp(target_host, target_port)
    result: dict[str, Any] = {
        "reachable": False,
        "tcp_open": tcp_open,
        "status_code": None,
        "error": "",
    }
    try:
        with urllib.request.urlopen(public_url, timeout=timeout) as response:
            result["reachable"] = True
            result["status_code"] = response.status
            return result
    except urllib.error.HTTPError as exc:
        result["reachable"] = True
        result["status_code"] = exc.code
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def _preview_url(request: Any | None, site: Any, suffix: str) -> str:
    if request is not None:
        return request.build_absolute_uri(f"/preview/{site.slug}{suffix}")
    return f"/preview/{site.slug}{suffix}"


def payload_cms_status(site: Any, request: Any | None = None) -> dict[str, Any]:
    public_url = payload_cms_public_url()
    probe = _probe_http(public_url, settings.PAYLOAD_CMS_HOST, settings.PAYLOAD_CMS_PORT)
    return {
        "enabled": settings.PAYLOAD_CMS_ENABLED,
        "installed": payload_cms_source_exists(),
        "dependencies_ready": payload_dependencies_ready(),
        "database_configured": payload_cms_database_configured(),
        "secret_configured": payload_cms_secret_configured(),
        "public_url": public_url,
        "host": settings.PAYLOAD_CMS_HOST,
        "port": settings.PAYLOAD_CMS_PORT,
        "admin_url": f"{public_url}/admin",
        "template": "website",
        "source_url": PAYLOAD_CMS_SOURCE_URL,
        "license": PAYLOAD_LICENSE,
        "install_command": payload_install_command(),
        "launch_command": payload_cms_launch_command(),
        "recommended_target_url": _preview_url(request, site, "/blog/"),
        **probe,
    }


def payload_ecommerce_status(site: Any, request: Any | None = None) -> dict[str, Any]:
    public_url = payload_ecommerce_public_url()
    probe = _probe_http(public_url, settings.PAYLOAD_ECOMMERCE_HOST, settings.PAYLOAD_ECOMMERCE_PORT)
    return {
        "enabled": settings.PAYLOAD_ECOMMERCE_ENABLED,
        "installed": payload_ecommerce_source_exists(),
        "dependencies_ready": payload_dependencies_ready(),
        "database_configured": payload_ecommerce_database_configured(),
        "secret_configured": payload_ecommerce_secret_configured(),
        "stripe_configured": payload_ecommerce_stripe_configured(),
        "public_url": public_url,
        "host": settings.PAYLOAD_ECOMMERCE_HOST,
        "port": settings.PAYLOAD_ECOMMERCE_PORT,
        "admin_url": f"{public_url}/admin",
        "template": "ecommerce",
        "source_url": PAYLOAD_ECOMMERCE_SOURCE_URL,
        "license": PAYLOAD_LICENSE,
        "install_command": payload_install_command(),
        "launch_command": payload_ecommerce_launch_command(),
        "recommended_target_url": _preview_url(request, site, "/shop/"),
        **probe,
    }
