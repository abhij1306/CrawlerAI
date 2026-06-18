from __future__ import annotations

from urllib.parse import urlparse

from app.services.config.extraction_rules import PAGE_URL_CURRENCY_HINTS_RAW


def currency_hint_from_page_url(page_url: object) -> str | None:
    code, _is_host_level = _currency_hint_from_page_url(page_url)
    return code


def detail_currency_hint_is_host_level(
    page_url: str,
    *,
    expected_currency: str,
) -> bool:
    code, is_host_level = _currency_hint_from_page_url(page_url)
    return code == expected_currency and is_host_level


def _currency_hint_from_page_url(page_url: object) -> tuple[str | None, bool]:
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").strip().lower()
    path_segments = {
        segment.strip().lower()
        for segment in str(parsed.path or "").split("/")
        if segment.strip()
    }
    if not hostname and not path_segments:
        return None, False
    for token, code in dict(PAGE_URL_CURRENCY_HINTS_RAW or {}).items():
        normalized_token = str(token).strip().lower()
        if not normalized_token:
            continue
        if normalized_token.startswith("/"):
            token_path_segments = {
                segment.strip().lower()
                for segment in normalized_token.split("/")
                if segment.strip()
            }
            if token_path_segments and token_path_segments <= path_segments:
                return str(code), False
            continue
        host_token, _, raw_path = normalized_token.partition("/")
        token_path_segments = {
            segment.strip().lower()
            for segment in raw_path.split("/")
            if segment.strip()
        }
        host_matches = hostname == host_token or hostname.endswith(f".{host_token}")
        path_matches = not token_path_segments or token_path_segments <= path_segments
        if host_matches and path_matches:
            return str(code), True
    return None, False
