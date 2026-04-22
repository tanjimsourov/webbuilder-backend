from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from urllib.parse import quote

from django.utils.crypto import constant_time_compare


def _normalize_base32(secret: str) -> str:
    value = (secret or "").strip().replace(" ", "").upper()
    if not value:
        return ""
    pad = len(value) % 8
    if pad:
        value = value + ("=" * (8 - pad))
    return value


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def build_totp_uri(*, secret: str, account_name: str, issuer: str) -> str:
    issuer_value = (issuer or "Website Builder").strip()
    account_value = (account_name or "user").strip()
    label = quote(f"{issuer_value}:{account_value}")
    return f"otpauth://totp/{label}?secret={quote(secret)}&issuer={quote(issuer_value)}&algorithm=SHA1&digits=6&period=30"


def _hotp(secret: str, counter: int, *, digits: int = 6) -> str:
    normalized_secret = _normalize_base32(secret)
    key = base64.b32decode(normalized_secret, casefold=True)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    code = code_int % (10**digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, *, period_seconds: int = 30, digits: int = 6, window: int = 1) -> bool:
    code_value = str(code or "").strip()
    if not code_value.isdigit() or len(code_value) != digits:
        return False
    now_counter = int(time.time() // period_seconds)
    for delta in range(-abs(window), abs(window) + 1):
        expected = _hotp(secret, now_counter + delta, digits=digits)
        if constant_time_compare(expected, code_value):
            return True
    return False


def generate_recovery_codes(*, count: int = 10) -> list[str]:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    codes: list[str] = []
    for _ in range(max(1, count)):
        chunk = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{chunk[:5]}-{chunk[5:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    normalized = str(code or "").strip().replace("-", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def verify_recovery_code(raw_code: str, code_hash: str) -> bool:
    candidate_hash = hash_recovery_code(raw_code)
    return constant_time_compare(candidate_hash, str(code_hash or ""))
