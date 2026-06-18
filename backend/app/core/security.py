# Password hashing, JWT handling, and encryption helpers.
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from app.core.config import settings
from cryptography.fernet import Fernet, InvalidToken
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from joserfc.jwt import JWTClaimsRegistry
from passlib.hash import pbkdf2_sha256

_PASSWORD_HASHER = PasswordHasher()
_ARGON2_PREFIXES = ("$argon2id$", "$argon2i$", "$argon2d$")


class TokenDecodeError(ValueError):
    """Raised when a JWT cannot be decoded or validated."""


def _jwt_key() -> OctKey:
    return OctKey.import_key(settings.jwt_secret_key)


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def _is_argon2_hash(hashed_password: str) -> bool:
    return str(hashed_password or "").startswith(_ARGON2_PREFIXES)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        if _is_argon2_hash(hashed_password):
            return _PASSWORD_HASHER.verify(hashed_password, password)
        return pbkdf2_sha256.verify(password, hashed_password)
    except (TypeError, ValueError, argon2_exceptions.Argon2Error):
        return False


def password_needs_rehash(hashed_password: str) -> bool:
    try:
        if _is_argon2_hash(hashed_password):
            return _PASSWORD_HASHER.check_needs_rehash(hashed_password)
        return True
    except (TypeError, ValueError, argon2_exceptions.Argon2Error):
        return False


def create_access_token(subject: str, *, token_version: int = 0) -> str:
    expires_at = datetime.now(UTC) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": subject, "exp": expires_at, "ver": token_version}
    return jwt.encode(
        {"alg": settings.jwt_algorithm},
        payload,
        _jwt_key(),
        algorithms=[settings.jwt_algorithm],
    )


def decode_access_token(token: str) -> dict[str, str | int]:
    try:
        decoded = jwt.decode(
            token,
            _jwt_key(),
            algorithms=[settings.jwt_algorithm],
        )
        JWTClaimsRegistry().validate(decoded.claims)
    except JoseError as exc:
        raise TokenDecodeError("Invalid token") from exc
    return dict(decoded.claims)


def _fernet() -> Fernet:
    key = settings.encryption_key.encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
    return Fernet(derived_key)


def _legacy_fernet() -> Fernet:
    key = settings.encryption_key.encode("utf-8")
    padded_key = base64.urlsafe_b64encode(key.ljust(32, b"0")[:32])
    return Fernet(padded_key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    token = value.encode("utf-8")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        return _legacy_fernet().decrypt(token).decode("utf-8")
