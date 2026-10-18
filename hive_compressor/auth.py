"""Small API-key auth helper.

Only SHA-256 hashes are configured on the server. Raw customer keys do not need
storage in this MVP.
"""

from __future__ import annotations

import hashlib
import hmac
import os


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def configured_hashes() -> set[str]:
    raw = os.getenv("HIVE_API_KEY_SHA256", "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def auth_required() -> bool:
    return os.getenv("HIVE_ALLOW_INSECURE_LOCAL", "0") != "1"


def validate_api_key(api_key: str | None) -> tuple[bool, str | None]:
    if not auth_required():
        identity = hash_api_key(api_key or "insecure-local")
        return True, identity

    allowed = configured_hashes()
    if not allowed or not api_key:
        return False, None

    candidate = hash_api_key(api_key)
    for expected in allowed:
        if hmac.compare_digest(candidate, expected):
            return True, candidate
    return False, None
