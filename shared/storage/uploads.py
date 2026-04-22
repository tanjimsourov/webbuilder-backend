from __future__ import annotations

import secrets
from pathlib import Path


def secure_media_upload_path(instance, filename: str) -> str:
    """Generate random server-side file names for uploads."""
    suffix = Path(str(filename or "")).suffix.lower()
    ext = suffix[1:] if suffix.startswith(".") else ""
    safe_ext = f".{ext}" if ext else ""
    token = secrets.token_hex(16)
    # Keep uploads in a non-executable, storage-only tree.
    return str(Path("objects") / "media" / token[:2] / f"{token}{safe_ext}")
