from __future__ import annotations

from backend_fastapi.api_key_crypto import (
    decrypt_session_api_key,
    encrypt_session_api_key,
    fernet_key_configured,
)


def test_encrypt_decrypt_roundtrip(test_fernet_key: str) -> None:
    assert fernet_key_configured()
    ct = encrypt_session_api_key("sk-ant-secret-value")
    assert ct is not None
    assert ct != "sk-ant-secret-value"
    assert decrypt_session_api_key(ct) == "sk-ant-secret-value"


def test_decrypt_legacy_plaintext(test_fernet_key: str) -> None:
    assert decrypt_session_api_key("sk-ant-plain-legacy") == "sk-ant-plain-legacy"
