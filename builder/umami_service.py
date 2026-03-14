from __future__ import annotations

import os
import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings


UMAMI_SOURCE_URL = "https://github.com/umami-software/umami"
UMAMI_LICENSE = "MIT"


def umami_root() -> Path:
    return settings.BASE_DIR.parent / "vendor" / "umami"


def umami_package_json() -> Path:
    return umami_root() / "package.json"


def umami_source_exists() -> bool:
    return umami_package_json().exists() and (umami_root() / "LICENSE").exists()


def umami_dependencies_ready() -> bool:
    return (umami_root() / "node_modules").exists()


def umami_database_configured() -> bool:
    return bool(os.environ.get("UMAMI_DATABASE_URL") or os.environ.get("DATABASE_URL"))


def umami_public_url() -> str:
    configured = (settings.UMAMI_PUBLIC_URL or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://{settings.UMAMI_HOST}:{settings.UMAMI_PORT}"


def umami_install_command() -> str:
    return "pnpm install"


def umami_launch_command() -> str:
    return "python manage.py run_umami"


def umami_node_binary() -> str:
    return shutil.which("pnpm.cmd") or shutil.which("pnpm") or "pnpm.cmd"


def _probe_tcp(host: str, port: int, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_umami(timeout: float = 1.5) -> dict[str, Any]:
    public_url = umami_public_url()
    parsed = urllib.parse.urlparse(public_url)
    host = parsed.hostname or settings.UMAMI_HOST
    port = parsed.port or settings.UMAMI_PORT
    tcp_open = _probe_tcp(host, port)
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


def umami_status(site: Any) -> dict[str, Any]:
    probe = probe_umami()
    domain = (getattr(site, "domain", "") or "").strip()
    return {
        "enabled": settings.UMAMI_ENABLED,
        "installed": umami_source_exists(),
        "dependencies_ready": umami_dependencies_ready(),
        "database_configured": umami_database_configured(),
        "public_url": umami_public_url(),
        "host": settings.UMAMI_HOST,
        "port": settings.UMAMI_PORT,
        "source_url": UMAMI_SOURCE_URL,
        "license": UMAMI_LICENSE,
        "install_command": umami_install_command(),
        "launch_command": umami_launch_command(),
        "recommended_domain": domain or f"{site.slug}.local",
        **probe,
    }
