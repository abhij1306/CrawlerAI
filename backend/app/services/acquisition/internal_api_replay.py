from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from urllib.parse import SplitResult, urlsplit

import httpx

from app.services.acquisition.browser_capture import classify_network_endpoint
from app.services.acquisition.runtime import get_shared_http_client
from app.services.config.domain_profiles import (
    INTERNAL_API_ENDPOINT_ALLOWED_METHODS,
    INTERNAL_API_ENDPOINT_FAMILY_KEY,
    INTERNAL_API_ENDPOINT_METHOD_KEY,
    INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY,
    INTERNAL_API_ENDPOINT_TYPE_KEY,
    INTERNAL_API_ENDPOINT_URL_KEY,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.extract.network_listing_mapper import extract_listing_rows_from_network
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.url_safety import validate_public_target

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
    seen: set[tuple[str, str]] = set()
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
        key = (
            str(endpoint.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or ""),
            str(endpoint.get(INTERNAL_API_ENDPOINT_URL_KEY) or ""),
        )
        if key in seen:
            continue
        if not _payload_extracts_surface(
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


async def _replay_endpoint(
    endpoint: Mapping[str, object],
    *,
    page_url: str,
    surface: str,
    requested_fields: list[str],
) -> dict[str, object] | None:
    method = str(endpoint.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or "GET").strip().upper()
    url = str(endpoint.get(INTERNAL_API_ENDPOINT_URL_KEY) or "").strip()
    if method not in INTERNAL_API_ENDPOINT_ALLOWED_METHODS or not url:
        return None
    if not await _is_safe_replay_url(url, page_url=page_url):
        return None
    try:
        client = await get_shared_http_client(proxy=None)
        response = await _request_replay_payload(client, method, url)
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
    if not _payload_extracts_surface(
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
    if normalize_domain(url) != normalize_domain(page_url):
        return False
    if _origin(parsed) != _origin(page_parsed):
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
    if normalize_domain(url) != normalize_domain(page_url):
        return {}
    endpoint: dict[str, object] = {
        INTERNAL_API_ENDPOINT_URL_KEY: url,
        INTERNAL_API_ENDPOINT_METHOD_KEY: method,
    }
    endpoint_type = str(payload.get(INTERNAL_API_ENDPOINT_TYPE_KEY) or "").strip()
    if endpoint_type:
        endpoint[INTERNAL_API_ENDPOINT_TYPE_KEY] = endpoint_type
    endpoint_family = str(payload.get(INTERNAL_API_ENDPOINT_FAMILY_KEY) or "").strip()
    if endpoint_family:
        endpoint[INTERNAL_API_ENDPOINT_FAMILY_KEY] = endpoint_family
    if source_run_id > 0:
        endpoint[INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY] = int(source_run_id)
    return endpoint


def _payload_extracts_surface(
    payload: dict[str, object],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str],
) -> bool:
    if "listing" in surface:
        return bool(
            extract_listing_rows_from_network(
                [payload],
                page_url=page_url,
                surface=surface,
                max_records=1,
            )
        )
    if "detail" in surface:
        return bool(
            map_network_payloads_to_fields(
                [payload],
                surface=surface,
                page_url=page_url,
                requested_fields=requested_fields,
            )
        )
    return False


__all__ = [
    "learned_internal_api_endpoints",
    "replay_internal_api_endpoints",
]
