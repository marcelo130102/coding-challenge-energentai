"""Symmetric encryption for session API keys at rest (Fernet).

Env ``SESSION_API_KEY_FERNET_KEY``: url-safe base64 key from ``Fernet.generate_key()``.

Session rows store ciphertext. Values passed into Docker are decrypted to plain
``ANTHROPIC_API_KEY`` inside the container (required by the Anthropic client).
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_ENV_SESSION_API_KEY_FERNET = "SESSION_API_KEY_FERNET_KEY"


def fernet_key_configured() -> bool:
    return bool(os.getenv(_ENV_SESSION_API_KEY_FERNET, "").strip())


def _fernet() -> Fernet:
    raw = os.getenv(_ENV_SESSION_API_KEY_FERNET, "").strip()
    if not raw:
        raise RuntimeError(f"{_ENV_SESSION_API_KEY_FERNET} is not set")
    return Fernet(raw.encode("utf-8"))


def encrypt_session_api_key(plain: str | None) -> str | None:
    """Encrypt for DB storage. Requires env key when called (orchestration path enforces first)."""
    if plain is None or plain == "":
        return None
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_session_api_key(stored: str | None) -> str | None:
    """Decrypt for Docker / internal use. Falls back to legacy plaintext if decrypt fails."""
    if stored is None or stored == "":
        return None
    if not fernet_key_configured():
        return stored
    try:
        return _fernet().decrypt(stored.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return stored
