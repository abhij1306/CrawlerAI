from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from urllib.parse import urlparse, urlunparse

import httpx

from app.services.config import ucp_audit as config
from app.services.network_resolution import build_async_http_client
from app.services.ucp_audit.types import UCPManifestResult

logger = logging.getLogger(__name__)


async def discover_ucp_manifest(domain: str) -> UCPManifestResult:
    target_url = _manifest_url(domain)
    result = await _fetch_manifest_page(target_url)
    if result is None:
        return UCPManifestResult(
            manifest_found=False,
            capabilities_declared=[],
            missing_required_capabilities=list(config.UCP_REQUIRED_CAPABILITIES),
            manifest_valid=False,
            raw_manifest=None,
            errors=[f"{config.UCP_MANIFEST_PATH} fetch failed"],
        )
    if getattr(result, "error", ""):
        return UCPManifestResult(
            manifest_found=False,
            capabilities_declared=[],
            missing_required_capabilities=list(config.UCP_REQUIRED_CAPABILITIES),
            manifest_valid=False,
            raw_manifest=None,
            errors=[str(result.error)],
        )
    if int(getattr(result, "status_code", 0) or 0) == 404:
        return UCPManifestResult(
            manifest_found=False,
            capabilities_declared=[],
            missing_required_capabilities=list(config.UCP_REQUIRED_CAPABILITIES),
            manifest_valid=False,
            raw_manifest=None,
            errors=[f"{config.UCP_MANIFEST_PATH} returned 404"],
        )
    raw_body = str(getattr(result, "html", "") or "")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return UCPManifestResult(
            manifest_found=True,
            capabilities_declared=[],
            missing_required_capabilities=list(config.UCP_REQUIRED_CAPABILITIES),
            manifest_valid=False,
            raw_manifest=None,
            errors=[str(exc)],
        )
    if not isinstance(payload, dict):
        return UCPManifestResult(
            manifest_found=True,
            capabilities_declared=[],
            missing_required_capabilities=list(config.UCP_REQUIRED_CAPABILITIES),
            manifest_valid=False,
            raw_manifest=None,
            errors=[type(payload).__name__],
        )
    declared = _declared_capabilities(payload)
    missing = _missing_required_capabilities(payload, declared)
    return UCPManifestResult(
        manifest_found=True,
        capabilities_declared=declared,
        missing_required_capabilities=missing,
        manifest_valid=not missing,
        raw_manifest=payload,
        errors=[],
    )


async def _fetch_manifest_page(url: str):
    try:
        async with build_async_http_client(
            follow_redirects=True,
            timeout=config.UCP_DISCOVERY_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(url)
        return SimpleNamespace(
            url=url,
            final_url=str(response.url),
            html=response.text,
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
        )
    except (httpx.HTTPError, OSError, TimeoutError, asyncio.TimeoutError) as exc:
        logger.debug("UCP manifest fetch failed for %s", url, exc_info=True)
        return SimpleNamespace(
            url=url,
            final_url=url,
            html="",
            status_code=0,
            content_type="",
            error=str(exc),
        )


def _manifest_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if not parsed.scheme:
        parsed = urlparse(f"{config.UCP_DEFAULT_URL_SCHEME}://{value}")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            config.UCP_MANIFEST_PATH,
            "",
            "",
            "",
        )
    )


def _declared_capabilities(payload: dict) -> list[str]:
    raw = payload.get("capabilities")
    if isinstance(raw, dict):
        values = raw.keys()
    elif isinstance(raw, list):
        values = raw
    else:
        services = _service_map(payload)
        values = services.keys() if services else []
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _service_map(payload: dict) -> dict:
    direct = payload.get("services")
    if isinstance(direct, dict):
        return direct
    nested = payload.get("ucp")
    if isinstance(nested, dict) and isinstance(nested.get("services"), dict):
        return nested["services"]
    return {}


def _missing_required_capabilities(payload: dict, declared: list[str]) -> list[str]:
    declared_set = set(declared)
    if _service_map(payload):
        return [
            item for item in config.UCP_REQUIRED_SERVICE_NAMES if item not in declared_set
        ]
    return [item for item in config.UCP_REQUIRED_CAPABILITIES if item not in declared_set]
