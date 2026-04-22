from __future__ import annotations

import hashlib
import hmac
import time


def sign_payload(secret: str, payload: bytes, *, timestamp: int | None = None) -> str:
    ts = int(timestamp or time.time())
    body = f"{ts}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_signature(
    secret: str,
    payload: bytes,
    signature_header: str,
    *,
    tolerance_seconds: int = 300,
) -> bool:
    if not secret or not signature_header:
        return False
    parts = {}
    for chunk in signature_header.split(","):
        key, sep, value = chunk.strip().partition("=")
        if sep and key and value:
            parts[key] = value
    try:
        timestamp = int(parts.get("t", "0"))
    except (TypeError, ValueError):
        return False
    expected = sign_payload(secret, payload, timestamp=timestamp)
    if not hmac.compare_digest(expected, signature_header):
        return False
    now = int(time.time())
    if abs(now - timestamp) > max(1, tolerance_seconds):
        return False
    return True
