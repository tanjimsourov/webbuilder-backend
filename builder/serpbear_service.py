from __future__ import annotations

import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings


SERPBEAR_SOURCE_URL = "https://github.com/towfiqi/serpbear"
SERPBEAR_LICENSE = "MIT"


def serpbear_root() -> Path:
    return settings.BASE_DIR.parent / "vendor" / "serpbear"


def serpbear_package_json() -> Path:
    return serpbear_root() / "package.json"


def serpbear_source_exists() -> bool:
    return serpbear_package_json().exists() and (serpbear_root() / "LICENSE").exists()


def serpbear_dependencies_ready() -> bool:
    return (serpbear_root() / "node_modules").exists()


def serpbear_public_url() -> str:
    configured = (settings.SERPBEAR_PUBLIC_URL or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"http://{settings.SERPBEAR_HOST}:{settings.SERPBEAR_PORT}"


def serpbear_install_command() -> str:
    return "npm.cmd install"


def serpbear_launch_command() -> str:
    return "python manage.py run_serpbear"


def serpbear_node_binary() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"


def _probe_tcp(host: str, port: int, timeout: float = 0.75) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_serpbear(timeout: float = 1.5) -> dict[str, Any]:
    public_url = serpbear_public_url()
    parsed = urllib.parse.urlparse(public_url)
    host = parsed.hostname or settings.SERPBEAR_HOST
    port = parsed.port or settings.SERPBEAR_PORT
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


def recommended_domain(site: Any) -> str:
    domain = (getattr(site, "domain", "") or "").strip()
    if domain:
        return domain.replace("https://", "").replace("http://", "").rstrip("/")
    return f"{site.slug}.local"


def serpbear_status(site: Any) -> dict[str, Any]:
    probe = probe_serpbear()
    return {
        "enabled": settings.SERPBEAR_ENABLED,
        "installed": serpbear_source_exists(),
        "dependencies_ready": serpbear_dependencies_ready(),
        "public_url": serpbear_public_url(),
        "host": settings.SERPBEAR_HOST,
        "port": settings.SERPBEAR_PORT,
        "source_url": SERPBEAR_SOURCE_URL,
        "license": SERPBEAR_LICENSE,
        "install_command": serpbear_install_command(),
        "launch_command": serpbear_launch_command(),
        "recommended_domain": recommended_domain(site),
        **probe,
    }
