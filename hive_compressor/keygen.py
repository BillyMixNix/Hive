"""Generate a customer API key and the server-side SHA-256 value."""

from __future__ import annotations

import secrets

from .auth import hash_api_key


def main() -> None:
    key = "hive_" + secrets.token_urlsafe(32)
    print("API key (show once):")
    print(key)
    print("\nServer env value:")
    print(f"HIVE_API_KEY_SHA256={hash_api_key(key)}")


if __name__ == "__main__":
    main()
