from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.acquisition.browser_capture import classify_network_endpoint
from app.acquisition.runtime import get_shared_http_client
from app.core.config.domain_profiles import (
    INTERNAL_API_ENDPOINT_ALLOWED_METHODS,
    INTERNAL_API_ENDPOINT_FAMILY_KEY,
    INTERNAL_API_ENDPOINT_METHOD_KEY,
    INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY,
    INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY,
    INTERNAL_API_ENDPOINT_SOURCE_ROUTE_KEY,
    INTERNAL_API_ENDPOINT_TYPE_KEY,
    INTERNAL_API_ENDPOINT_URL_KEY,
    INTERNAL_API_REPLAY_BLOCKED_PATH_MARKERS,
    INTERNAL_API_REPLAY_FIRST_PARTY_SUBDOMAINS,
    INTERNAL_API_REPLAY_ROUTE_QUERY_KEYS,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.domain_utils import normalize_domain
from app.core.records.field_url_normalization import registrable_host
from app.extraction.json_walk import walk_json
from app.core.url_safety import validate_public_target

logger = logging.getLogger(__name__)


def learned_internal_api_endpoints(
    *,
    network_payloads: list[dict[str, object]] | None,
    surface: str,
    page_url: str,
    requested_fields: list[str],
    source_run_id: int,
) -> list[dict[str, object]]:
    normalized_surface = str(surface or "").strip().lower()
    if not network_payloads:
        return []
    endpoints: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    max_endpoints = max(
        1,
        int(crawler_runtime_settings.internal_api_replay_max_endpoints),
    )
    for payload in list(network_payloads):
        endpoint = _endpoint_from_payload(
            payload,
            page_url=page_url,
            source_run_id=source_run_id,
        )
        if not endpoint:
            continue
        key = endpoint_identity(endpoint)
        if key in seen:
            continue
        if not payload_extracts_surface(
            payload,
            surface=normalized_surface,
            page_url=page_url,
            requested_fields=requested_fields,
        ):
            continue
        seen.add(key)
        endpoints.append(endpoint)
        if len(endpoints) >= max_endpoints:
            break
    return endpoints


async def replay_internal_api_endpoints(
    *,
    page_url: str,
    surface: str,
    endpoints: list[dict[str, object]] | tuple[dict[str, object], ...],
    requested_fields: list[str],
) -> dict[str, object] | None:
    if not bool(crawler_runtime_settings.internal_api_replay_enabled):
        return None
    for endpoint in list(endpoints or [])[
        : max(1, int(crawler_runtime_settings.internal_api_replay_max_endpoints))
    ]:
        payload = await _replay_endpoint(
            endpoint,
            page_url=page_url,
            surface=surface,
            requested_fields=requested_fields,
        )
        if payload is not None:
            return payload
    return None


async def verify_internal_api_endpoints(
    *,
    page_url: str,
    surface: str,
    endpoints: list[dict[str, object]],
    requested_fields: list[str],
) -> list[dict[str, object]]:
    """Keep only captured endpoints that also work without browser state."""
    verified: list[dict[str, object]] = []
    for endpoint in endpoints:
        payload = await _replay_endpoint(
            endpoint,
            page_url=page_url,
            surface=surface,
            requested_fields=requested_fields,
        )
        if payload is not None:
            verified.append(endpoint)
    return verified


def replay_endpoint_identities_for_page(
    endpoints: object,
    *,
    page_url: str,
) -> list[tuple[str, str, str, str]]:
    if not isinstance(endpoints, (list, tuple)):
        return []
    source_route = _route_identity(page_url)
    return [
        endpoint_identity(endpoint)
        for endpoint in endpoints
        if isinstance(endpoint, Mapping)
        and str(endpoint.get(INTERNAL_API_ENDPOINT_SOURCE_ROUTE_KEY) or "")
        == source_route
    ]


async def _replay_endpoint(
    endpoint: Mapping[str, object],
    *,
    page_url: str,
    surface: str,
    requested_fields: list[str],
) -> dict[str, object] | None:
    method = (
        str(endpoint.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or "GET").strip().upper()
    )
    url = str(endpoint.get(INTERNAL_API_ENDPOINT_URL_KEY) or "").strip()
    if method not in INTERNAL_API_ENDPOINT_ALLOWED_METHODS or not url:
        return None
    if str(
        endpoint.get(INTERNAL_API_ENDPOINT_SOURCE_ROUTE_KEY) or ""
    ) != _route_identity(page_url):
        return None
    request_json = endpoint.get(INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY)
    if method == "POST" and not isinstance(request_json, Mapping):
        return None
    if _blocked_replay_path(url):
        return None
    if not await _is_safe_replay_url(url, page_url=page_url):
        return None
    try:
        client = await get_shared_http_client(proxy=None)
        response = await _request_replay_payload(
            client,
            method,
            url,
            request_json=dict(request_json)
            if isinstance(request_json, Mapping)
            else None,
        )
        body = _decode_response_body(response)
    except (httpx.HTTPError, OSError, ValueError):
        logger.debug("Internal API replay failed for %s", url, exc_info=True)
        return None
    if response.status_code >= 400 or body in (None, "", [], {}):
        return None
    endpoint_info = classify_network_endpoint(response_url=url, surface=surface)
    payload: dict[str, object] = {
        INTERNAL_API_ENDPOINT_URL_KEY: url,
        INTERNAL_API_ENDPOINT_METHOD_KEY: method,
        "status": int(response.status_code),
        "content_type": str(response.headers.get("content-type", "application/json")),
        INTERNAL_API_ENDPOINT_TYPE_KEY: str(
            endpoint.get(INTERNAL_API_ENDPOINT_TYPE_KEY)
            or endpoint_info.get("type")
            or "generic_json"
        ),
        INTERNAL_API_ENDPOINT_FAMILY_KEY: str(
            endpoint.get(INTERNAL_API_ENDPOINT_FAMILY_KEY)
            or endpoint_info.get("family")
            or ""
        ),
        "body": body,
    }
    if isinstance(request_json, Mapping):
        payload[INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY] = dict(request_json)
    if not payload_extracts_surface(
        payload,
        surface=str(surface or "").strip().lower(),
        page_url=page_url,
        requested_fields=requested_fields,
    ):
        return None
    return payload


def _decode_response_body(response: httpx.Response) -> object | None:
    try:
        return response.json()
    except json.JSONDecodeError:
        return None


async def _request_replay_payload(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    request_json: dict[str, object] | None = None,
) -> httpx.Response:
    timeout = max(
        0.1,
        float(crawler_runtime_settings.internal_api_replay_timeout_seconds),
    )
    max_bytes = max(
        1,
        int(crawler_runtime_settings.browser_capture_max_network_payload_bytes),
    )
    chunks: list[bytes] = []
    total = 0
    async with client.stream(
        method,
        url,
        json=request_json,
        timeout=timeout,
        follow_redirects=False,
    ) as response:
        if 300 <= response.status_code < 400:
            raise ValueError("internal API replay redirects are not allowed")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("internal API replay response exceeded size limit")
            chunks.append(chunk)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            request=response.request,
        )


async def _is_safe_replay_url(url: str, *, page_url: str) -> bool:
    parsed = urlsplit(url)
    page_parsed = urlsplit(page_url)
    if parsed.scheme.lower() != "https" or page_parsed.scheme.lower() != "https":
        return False
    if not _is_allowed_first_party_origin(parsed, page_parsed):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        await validate_public_target(url)
    except ValueError:
        return False
    return True


def _origin(parsed: SplitResult) -> tuple[str, str, int]:
    scheme = parsed.scheme.lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    return scheme, str(parsed.hostname or "").lower(), port


def _is_allowed_first_party_origin(
    endpoint: SplitResult,
    page: SplitResult,
) -> bool:
    if endpoint.scheme.casefold() != page.scheme.casefold():
        return False
    if _origin(endpoint)[2] != _origin(page)[2]:
        return False
    endpoint_host = str(endpoint.hostname or "").casefold().strip(".")
    page_host = str(page.hostname or "").casefold().strip(".")
    if not endpoint_host or not page_host:
        return False
    if endpoint_host == page_host:
        return True
    endpoint_site = registrable_host(endpoint.geturl())
    page_site = registrable_host(page.geturl())
    if not endpoint_site or endpoint_site != page_site:
        return False
    return _first_party_subdomain(endpoint_host, endpoint_site) in {
        "",
        *INTERNAL_API_REPLAY_FIRST_PARTY_SUBDOMAINS,
    } and _first_party_subdomain(page_host, page_site) in {
        "",
        *INTERNAL_API_REPLAY_FIRST_PARTY_SUBDOMAINS,
    }


def _first_party_subdomain(host: str, site: str) -> str:
    if host == site:
        return ""
    suffix = f".{site}"
    if not host.endswith(suffix):
        return "!invalid!"
    return host[: -len(suffix)]


def _endpoint_from_payload(
    payload: object,
    *,
    page_url: str,
    source_run_id: int,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    url = str(payload.get(INTERNAL_API_ENDPOINT_URL_KEY) or "").strip()
    method = str(payload.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or "GET").strip().upper()
    if not url or method not in INTERNAL_API_ENDPOINT_ALLOWED_METHODS:
        return {}
    endpoint_url = urlsplit(url)
    page = urlsplit(page_url)
    if endpoint_url.scheme.casefold() != "https" or page.scheme.casefold() != "https":
        return {}
    if not _is_allowed_first_party_origin(endpoint_url, page):
        return {}
    if _blocked_replay_path(url):
        return {}
    endpoint: dict[str, object] = {
        INTERNAL_API_ENDPOINT_URL_KEY: url,
        INTERNAL_API_ENDPOINT_METHOD_KEY: method,
        INTERNAL_API_ENDPOINT_SOURCE_ROUTE_KEY: _route_identity(page_url),
    }
    endpoint_type = str(payload.get(INTERNAL_API_ENDPOINT_TYPE_KEY) or "").strip()
    if method == "POST" and endpoint_type not in {
        "graphql",
        "job_api",
        "product_api",
    }:
        return {}
    if endpoint_type:
        endpoint[INTERNAL_API_ENDPOINT_TYPE_KEY] = endpoint_type
    endpoint_family = str(payload.get(INTERNAL_API_ENDPOINT_FAMILY_KEY) or "").strip()
    if endpoint_family:
        endpoint[INTERNAL_API_ENDPOINT_FAMILY_KEY] = endpoint_family
    request_json = payload.get(INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY)
    if method == "POST" and isinstance(request_json, Mapping):
        endpoint[INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY] = dict(request_json)
    elif method == "POST":
        return {}
    if source_run_id > 0:
        endpoint[INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY] = int(source_run_id)
    return endpoint


def payload_extracts_surface(
    payload: dict[str, object],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str],
) -> bool:
    if "listing" in surface:
        return _payload_has_listing_row(payload, page_url=page_url)
    if "detail" in surface:
        return _payload_has_detail_object(
            payload,
            surface=surface,
            page_url=page_url,
            requested_fields=requested_fields,
        )
    return False


def _payload_has_listing_row(payload: dict[str, object], *, page_url: str) -> bool:
    page_domain = normalize_domain(page_url)
    body = payload.get("body", payload)
    if not _payload_mentions_page_route(body, page_url):
        return False
    for node in walk_json(body):
        if not isinstance(node.value, dict):
            continue
        row = node.value
        title = row.get("title") or row.get("name") or row.get("jobTitle")
        url = (
            row.get("url") or row.get("href") or row.get("link") or row.get("applyUrl")
        )
        if not title or not url:
            continue
        text_url = str(url)
        if text_url.startswith("/"):
            return True
        if normalize_domain(text_url) == page_domain:
            return True
    return False


def _payload_mentions_page_route(body: object, page_url: str) -> bool:
    expected = _route_identity(page_url)
    if not expected:
        return False
    for node in walk_json(body):
        if isinstance(node.value, str) and _route_identity(node.value) == expected:
            return True
    return False


def _payload_has_detail_object(
    payload: dict[str, object],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str],
) -> bool:
    requested = {
        str(field or "").strip().lower()
        for field in requested_fields
        if str(field or "").strip()
    }
    commerce_keys = {
        "name",
        "title",
        "sku",
        "price",
        "pricecurrency",
        "currency",
        "offers",
    }
    job_keys = {
        "title",
        "jobtitle",
        "hiringorganization",
        "company",
        "joblocation",
        "location",
    }
    key_set = job_keys if "job" in surface else commerce_keys
    for node in walk_json(payload.get("body", payload)):
        if not isinstance(node.value, dict):
            continue
        keys = {str(key or "").strip().lower() for key in node.value}
        if "ecommerce" in surface and not _commerce_detail_keys_are_product_like(keys):
            continue
        if not _record_url_matches_page(node.value, page_url):
            continue
        if requested and keys & requested:
            return True
        if keys & key_set:
            return True
    return False


def _record_url_matches_page(row: Mapping[str, object], page_url: str) -> bool:
    """A replay response must identify the requested detail route.

    Domain-wide endpoint memory must not turn a successful response for product
    A into a result for product B.  An unidentifiable response falls through to
    normal acquisition instead of being published from stale network data.
    """
    expected = _route_identity(page_url)
    if not expected:
        return False
    for key in ("url", "href", "link", "canonicalUrl", "productUrl", "jobUrl"):
        candidate = row.get(key)
        if isinstance(candidate, str) and _route_identity(candidate) == expected:
            return True
    return False


def _route_identity(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.scheme or not parsed.hostname or not parsed.path:
        return ""
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() in INTERNAL_API_REPLAY_ROUTE_QUERY_KEYS
        )
    )
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.hostname.casefold(),
            parsed.path.rstrip("/"),
            query,
            "",
        )
    )


def endpoint_identity(endpoint: Mapping[str, object]) -> tuple[str, str, str, str]:
    request_json = endpoint.get(INTERNAL_API_ENDPOINT_REQUEST_JSON_KEY)
    request_identity = (
        json.dumps(request_json, sort_keys=True, separators=(",", ":"))
        if isinstance(request_json, Mapping)
        else ""
    )
    return (
        str(endpoint.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or "").strip().upper(),
        str(endpoint.get(INTERNAL_API_ENDPOINT_URL_KEY) or "").strip(),
        str(endpoint.get(INTERNAL_API_ENDPOINT_SOURCE_ROUTE_KEY) or "").strip(),
        request_identity,
    )


def _blocked_replay_path(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(marker in path for marker in INTERNAL_API_REPLAY_BLOCKED_PATH_MARKERS)


def _commerce_detail_keys_are_product_like(keys: set[str]) -> bool:
    strong_keys = {
        "sku",
        "price",
        "pricecurrency",
        "currency",
        "offers",
        "variants",
        "hasvariant",
    }
    return bool(keys & strong_keys)


__all__ = [
    "learned_internal_api_endpoints",
    "endpoint_identity",
    "payload_extracts_surface",
    "replay_endpoint_identities_for_page",
    "replay_internal_api_endpoints",
    "verify_internal_api_endpoints",
]
