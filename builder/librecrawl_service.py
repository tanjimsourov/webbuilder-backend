from __future__ import annotations

import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings


LIBRECRAWL_SOURCE_URL = "https://github.com/PhialsBasement/LibreCrawl"
LIBRECRAWL_LICENSE = "MIT"


def librecrawl_root() -> Path:
    return settings.BASE_DIR.parent / "vendor" / "librecrawl"


def librecrawl_main_path() -> Path:
    return librecrawl_root() / "main.py"


def librecrawl_requirements_path() -> Path:
    return settings.BASE_DIR / "requirements-librecrawl.txt"


def librecrawl_installed() -> bool:
    return librecrawl_main_path().exists() and (librecrawl_root() / "LICENSE").exists()


def librecrawl_public_url() -> str:
    configured = (settings.LIBRECRAWL_PUBLIC_URL or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://{settings.LIBRECRAWL_HOST}:{settings.LIBRECRAWL_PORT}"


def librecrawl_launch_command() -> str:
    return f"{Path(sys.executable).name} manage.py run_librecrawl"


def librecrawl_install_command() -> str:
    return f"{Path(sys.executable).name} -m pip install -r requirements-librecrawl.txt"


def _probe_tcp(host: str, port: int, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_librecrawl(timeout: float = 1.5) -> dict[str, Any]:
    public_url = librecrawl_public_url()
    parsed = urllib.parse.urlparse(public_url)
    host = parsed.hostname or settings.LIBRECRAWL_HOST
    port = parsed.port or settings.LIBRECRAWL_PORT
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


def recommended_target_url(site: Any, request: Any | None = None) -> str:
    domain = (getattr(site, "domain", "") or "").strip()
    if domain:
        if domain.startswith(("http://", "https://")):
            return domain.rstrip("/")
        return f"https://{domain}"
    if request is not None:
        return request.build_absolute_uri(f"/preview/{site.slug}/").rstrip("/")
    return f"/preview/{site.slug}/"


def librecrawl_status(site: Any, request: Any | None = None) -> dict[str, Any]:
    probe = probe_librecrawl()
    return {
        "enabled": settings.LIBRECRAWL_ENABLED,
        "installed": librecrawl_installed(),
        "public_url": librecrawl_public_url(),
        "host": settings.LIBRECRAWL_HOST,
        "port": settings.LIBRECRAWL_PORT,
        "local_mode": settings.LIBRECRAWL_LOCAL_MODE,
        "source_url": LIBRECRAWL_SOURCE_URL,
        "license": LIBRECRAWL_LICENSE,
        "launch_command": librecrawl_launch_command(),
        "install_command": librecrawl_install_command(),
        "recommended_target_url": recommended_target_url(site, request),
        **probe,
    }
