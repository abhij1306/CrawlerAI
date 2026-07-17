from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from urllib.parse import parse_qsl, urljoin, urlsplit

import httpx

from app.acquisition.runtime import curl_fetch, get_shared_http_client
from app.core.config import variant_policy
from app.core.domain_utils import normalize_domain
from app.core.url_safety import validate_public_target

logger = logging.getLogger(__name__)

FetchVariantEndpoint = Callable[[str], Awaitable[dict[str, object] | None]]


async def expand_sfcc_variant_endpoints(
    *,
    page_url: str,
    html_text: str,
    existing_payloads: list[dict[str, object]] | None = None,
    fetch_endpoint: FetchVariantEndpoint | None = None,
    proxy: str | None = None,
) -> list[dict[str, object]]:
    urls = await discover_sfcc_variant_endpoint_urls(
        page_url=page_url,
        html_text=html_text,
        existing_payloads=existing_payloads,
    )
    if not urls:
        return []
    out: list[dict[str, object]] = []
    for url in urls:
        payload = (
            await fetch_endpoint(url)
            if fetch_endpoint is not None
            else await _fetch_variant_endpoint(url, proxy=proxy)
        )
        if payload is not None:
            out.append(payload)
    return out


async def discover_sfcc_variant_endpoint_urls(
    *,
    page_url: str,
    html_text: str,
    existing_payloads: list[dict[str, object]] | None = None,
) -> list[str]:
    existing_urls = {
        str(payload.get("url") or "").strip()
        for payload in existing_payloads or []
        if isinstance(payload, Mapping)
    }
    out: list[str] = []
    seen: set[str] = set()
    page_codes = _page_product_codes(page_url)
    for raw_url in _raw_product_variation_urls(html_text):
        url = _normalize_candidate_url(page_url, raw_url)
        if url in seen or url in existing_urls:
            continue
        if not _same_origin_sfcc_url(page_url, url):
            continue
        if not _candidate_has_variant_axis_value(url):
            continue
        if not _candidate_matches_page_product(url, page_codes=page_codes):
            continue
        if not await _safe_public_url(url):
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= max(1, int(variant_policy.SFCC_VARIANT_ENDPOINT_MAX_URLS)):
            break
    return out


def _raw_product_variation_urls(html_text: str) -> tuple[str, ...]:
    token = re.escape(variant_policy.SFCC_VARIANT_ENDPOINT_PATH_TOKEN)
    patterns = (
        rf'(?P<url>https?://[^"\'<>\s]*{token}[^"\'<>\s]*)',
        rf'(?P<url>//[^"\'<>\s]*{token}[^"\'<>\s]*)',
        rf'(?P<url>/[^"\'<>\s]*{token}[^"\'<>\s]*)',
    )
    found: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html_text or "", flags=re.I):
            value = match.group("url").rstrip(">,)")
            if value:
                found.append(value)
    return tuple(dict.fromkeys(found))


def _normalize_candidate_url(page_url: str, raw_url: str) -> str:
    value = html.unescape(raw_url).replace("\\/", "/").strip()
    # One optional backslash per trailing junk char (not per run) keeps the
    # pattern free of nested quantifiers (ReDoS) while trimming the same text.
    value = re.sub(r"(?:\\?[\"'}\]])+$", "", value)
    return urljoin(page_url, value)


def _same_origin_sfcc_url(page_url: str, candidate_url: str) -> bool:
    page = urlsplit(page_url)
    candidate = urlsplit(candidate_url)
    if not candidate.scheme or not candidate.hostname:
        return False
    if candidate.scheme.lower() != page.scheme.lower():
        return False
    if normalize_domain(candidate_url) != normalize_domain(page_url):
        return False
    page_port = page.port or (443 if page.scheme.lower() == "https" else 80)
    candidate_port = candidate.port or (
        443 if candidate.scheme.lower() == "https" else 80
    )
    return page_port == candidate_port and (
        variant_policy.SFCC_VARIANT_ENDPOINT_PATH_TOKEN.casefold()
        in candidate.path.casefold()
    )


def _candidate_matches_page_product(
    candidate_url: str, *, page_codes: frozenset[str]
) -> bool:
    if not page_codes:
        return True
    query = {
        key.casefold(): value
        for key, value in parse_qsl(
            urlsplit(candidate_url).query, keep_blank_values=False
        )
    }
    pid = str(query.get("pid") or "").strip().casefold()
    if pid:
        return pid in page_codes
    dwvar_codes: list[str] = []
    for key in query:
        suffix = key.casefold().removeprefix("dwvar_")
        embedded_code, separator, _axis = suffix.partition("_")
        if key.casefold().startswith("dwvar_") and separator:
            dwvar_codes.append(embedded_code)
    if dwvar_codes:
        return any(code in page_codes for code in dwvar_codes)
    return True


def _candidate_has_variant_axis_value(candidate_url: str) -> bool:
    return any(
        key.casefold().startswith(("dwvar_", "attribute_")) and bool(value)
        for key, value in parse_qsl(
            urlsplit(candidate_url).query,
            keep_blank_values=False,
        )
    )


def _page_product_codes(page_url: str) -> frozenset[str]:
    path = urlsplit(page_url).path
    return frozenset(
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9]{6,}", path)
        if any(char.isdigit() for char in token)
    )


async def _safe_public_url(url: str) -> bool:
    try:
        await validate_public_target(url)
    except ValueError:
        return False
    return True


async def _fetch_variant_endpoint(
    url: str,
    *,
    proxy: str | None = None,
) -> dict[str, object] | None:
    try:
        client = await get_shared_http_client(proxy=proxy)
        response = await _request_json(client, url)
    except (httpx.TransportError, OSError):
        payload = await _fetch_variant_endpoint_with_curl(url, proxy=proxy)
        if payload is None:
            logger.debug(
                "SFCC variant endpoint expansion failed for %s",
                url,
                exc_info=True,
            )
        return payload
    if response.status_code >= 400:
        return None
    try:
        body = response.json()
    except json.JSONDecodeError:
        return None
    if body in (None, "", [], {}):
        return None
    return {
        "url": url,
        "method": "GET",
        "status": int(response.status_code),
        "content_type": str(response.headers.get("content-type", "application/json")),
        "type": variant_policy.SFCC_VARIANT_ENDPOINT_TYPE,
        "family": variant_policy.SFCC_VARIANT_ENDPOINT_FAMILY,
        "body": body,
    }


async def _fetch_variant_endpoint_with_curl(
    url: str,
    *,
    proxy: str | None = None,
) -> dict[str, object] | None:
    try:
        result = await curl_fetch(
            url,
            max(0.1, float(variant_policy.SFCC_VARIANT_ENDPOINT_TIMEOUT_SECONDS)),
            proxy=proxy,
        )
        body = json.loads(str(result.html or ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if result.status_code >= 400 or body in (None, "", [], {}):
        return None
    return {
        "url": url,
        "method": "GET",
        "status": int(result.status_code),
        "content_type": str(result.content_type or "application/json"),
        "type": variant_policy.SFCC_VARIANT_ENDPOINT_TYPE,
        "family": variant_policy.SFCC_VARIANT_ENDPOINT_FAMILY,
        "body": body,
    }


async def _request_json(client: httpx.AsyncClient, url: str) -> httpx.Response:
    timeout = max(0.1, float(variant_policy.SFCC_VARIANT_ENDPOINT_TIMEOUT_SECONDS))
    max_bytes = max(1, int(variant_policy.SFCC_VARIANT_ENDPOINT_MAX_BYTES))
    chunks: list[bytes] = []
    total = 0
    async with client.stream(
        "GET", url, timeout=timeout, follow_redirects=False
    ) as response:
        if 300 <= response.status_code < 400:
            raise ValueError("variant endpoint redirects are not allowed")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("variant endpoint response exceeded size limit")
            chunks.append(chunk)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            request=response.request,
        )
