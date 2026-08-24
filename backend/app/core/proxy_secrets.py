"""Canonical proxy credential sealing and URL redaction."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from urllib.parse import SplitResult, urlsplit, urlunsplit

from cryptography.fernet import InvalidToken

from app.core.config.proxy_secrets import (
    PROXY_SECRET_PAYLOAD_VERSION,
    PROXY_SECRET_REF_CIPHERTEXT_KEY,
    PROXY_SECRET_REF_ENDPOINT_KEY,
    PROXY_SECRET_REF_INDEX_KEY,
)
from app.core.security import decrypt_secret, encrypt_secret

_SCHEME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-"
)
_URL_TERMINATORS = frozenset(" \t\r\n<>\"'")


def _host_port(parsed) -> str:
    host = str(parsed.hostname or "")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return host


def strip_url_userinfo(value: object, *, masked: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        host = _host_port(parsed)
    except ValueError:
        return "REDACTED" if "@" in raw else raw
    if not parsed.scheme or not host:
        return "REDACTED" if "@" in raw else raw
    if parsed.username is None and parsed.password is None and "@" not in parsed.netloc:
        return raw
    netloc = f"***:***@{host}" if masked else host
    return urlunsplit(
        SplitResult(
            parsed.scheme,
            netloc,
            parsed.path,
            "" if masked else parsed.query,
            "" if masked else parsed.fragment,
        )
    )


def redact_secret_text(value: object) -> str:
    """Remove URL userinfo from arbitrary log, exception, and diagnostic text."""
    text = str(value or "")
    cursor = 0
    redacted: list[str] = []
    while (separator := text.find("://", cursor)) >= 0:
        start = separator - 1
        while start >= cursor and text[start] in _SCHEME_CHARS:
            start -= 1
        start += 1
        scheme = text[start:separator]
        if not scheme or not scheme[0].isalpha():
            redacted.append(text[cursor : separator + 3])
            cursor = separator + 3
            continue
        end = separator + 3
        while end < len(text) and text[end] not in _URL_TERMINATORS:
            end += 1
        candidate = text[start:end]
        redacted.append(text[cursor:start])
        redacted.append(
            strip_url_userinfo(candidate, masked=True)
            if "@" in candidate
            else candidate
        )
        cursor = end
    redacted.append(text[cursor:])
    return "".join(redacted)


def seal_proxy_urls(
    proxy_urls: Sequence[str],
) -> tuple[list[str], list[dict[str, object]]]:
    endpoints: list[str] = []
    references: list[dict[str, object]] = []
    for index, value in enumerate(proxy_urls):
        raw = str(value or "").strip()
        endpoint = strip_url_userinfo(raw)
        endpoints.append(endpoint)
        try:
            parsed = urlsplit(raw)
        except ValueError:
            continue
        if "@" not in parsed.netloc:
            continue
        userinfo = parsed.netloc.rsplit("@", maxsplit=1)[0]
        payload = json.dumps(
            {
                "v": PROXY_SECRET_PAYLOAD_VERSION,
                "endpoint": endpoint,
                "userinfo": userinfo,
            },
            separators=(",", ":"),
        )
        references.append(
            {
                PROXY_SECRET_REF_INDEX_KEY: index,
                PROXY_SECRET_REF_ENDPOINT_KEY: endpoint,
                PROXY_SECRET_REF_CIPHERTEXT_KEY: encrypt_secret(payload),
            }
        )
    return endpoints, references


def resolve_proxy_urls(endpoints: Sequence[object], references: object) -> list[str]:
    reference_by_index = (
        {
            int(str(row.get(PROXY_SECRET_REF_INDEX_KEY))): row
            for row in references
            if isinstance(row, Mapping)
            and str(row.get(PROXY_SECRET_REF_INDEX_KEY, "")).isdigit()
        }
        if isinstance(references, list)
        else {}
    )
    resolved: list[str] = []
    for index, value in enumerate(endpoints):
        endpoint = str(value or "").strip()
        if not endpoint:
            continue
        reference = reference_by_index.get(index)
        if reference is None:
            resolved.append(endpoint)
            continue
        restored = _resolve_proxy_reference(endpoint, reference)
        if restored is not None:
            resolved.append(restored)
    return resolved


def _resolve_proxy_reference(
    endpoint: str, reference: Mapping[str, object]
) -> str | None:
    if str(reference.get(PROXY_SECRET_REF_ENDPOINT_KEY) or "") != endpoint:
        return None
    try:
        payload = json.loads(
            decrypt_secret(str(reference.get(PROXY_SECRET_REF_CIPHERTEXT_KEY) or ""))
        )
    except (InvalidToken, ValueError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("v") != PROXY_SECRET_PAYLOAD_VERSION
        or payload.get("endpoint") != endpoint
        or not isinstance(payload.get("userinfo"), str)
    ):
        return None
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        return None
    host = _host_port(parsed)
    if not parsed.scheme or not host:
        return None
    return urlunsplit(
        SplitResult(
            parsed.scheme,
            f"{payload['userinfo']}@{host}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
