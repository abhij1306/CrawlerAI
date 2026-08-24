from __future__ import annotations

import pytest

import base64
import hashlib

from cryptography.fernet import Fernet
from app.core import security

LEGACY_PASSWORD_HASH = (
    "$pbkdf2-sha256$29000$Y3Jhd2xlcmFpLWxlZ2FjeQ$"
    "FKzppnMcKRAdi0/C4oWT1eO0ojNLGaL4Y.vTbT8Zxrk"
)


@pytest.mark.unit
def test_password_hash_verify_roundtrip() -> None:
    hashed = security.hash_password("correct horse battery staple")

    assert "argon2" in hashed
    assert security.verify_password("correct horse battery staple", hashed) is True
    assert security.verify_password("wrong password", hashed) is False


@pytest.mark.unit
def test_password_needs_rehash_returns_true_for_legacy_pbkdf2_hash() -> None:
    assert security.password_needs_rehash(LEGACY_PASSWORD_HASH) is True
    assert security.verify_password(
        "correct horse battery staple", LEGACY_PASSWORD_HASH
    )
    assert not security.verify_password("wrong", LEGACY_PASSWORD_HASH)


@pytest.mark.unit
@pytest.mark.parametrize(
    "malicious_hash",
    [
        "$pbkdf2-sha256$1000001$Y3Jhd2xlcmFpLWxlZ2FjeQ$FKzppnMcKRAdi0/"
        + "C4oWT1eO0ojNLGaL4Y.vTbT8Zxrk",
        "$pbkdf2-sha256$29000$c2hvcnQ$FKzppnMcKRAdi0/C4oWT1eO0ojNLGaL4Y.vTbT8Zxrk",
        "$pbkdf2-sha256$29000$not_valid*$also_invalid*",
    ],
)
def test_legacy_pbkdf2_verifier_rejects_malformed_or_excessive_hashes(
    malicious_hash: str,
) -> None:
    assert security.verify_password("password", malicious_hash) is False


@pytest.mark.unit
def test_access_token_roundtrip(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "jwt_secret_key", "test-jwt-secret")
    monkeypatch.setattr(security.settings, "jwt_algorithm", "HS256")
    monkeypatch.setattr(security.settings, "jwt_expire_hours", 1)

    token = security.create_access_token("user-123", token_version=7)
    payload = security.decode_access_token(token)

    assert payload["sub"] == "user-123"
    assert payload["ver"] == 7


@pytest.mark.unit
def test_encrypt_secret_roundtrip_uses_sha256_key_derivation(monkeypatch) -> None:
    raw_key = "short-but-stable-test-key"
    monkeypatch.setattr(security.settings, "encryption_key", raw_key)

    encrypted = security.encrypt_secret("provider-secret")

    assert security.decrypt_secret(encrypted) == "provider-secret"
    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(raw_key.encode("utf-8")).digest()
    )
    assert Fernet(derived_key).decrypt(encrypted.encode("utf-8")) == b"provider-secret"


@pytest.mark.unit
def test_decrypt_secret_supports_legacy_padded_key_derivation(monkeypatch) -> None:
    raw_key = "short-but-stable-test-key"
    monkeypatch.setattr(security.settings, "encryption_key", raw_key)
    legacy_key = base64.urlsafe_b64encode(raw_key.encode("utf-8").ljust(32, b"0")[:32])
    encrypted = Fernet(legacy_key).encrypt(b"provider-secret").decode("utf-8")

    assert security.decrypt_secret(encrypted) == "provider-secret"
