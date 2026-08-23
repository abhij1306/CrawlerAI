from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.acquisition.browser_runtime import SharedBrowserRuntime
from app.acquisition.runtime import (
    classify_block_from_headers,
    classify_blocked_page,
    copy_headers,
    curl_fetch,
    http_fetch,
)
from app.core.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS,
    BROWSER_SURFACE_PROBE_TARGET_BODY_ARTIFACT_LIMIT,
    BROWSER_SURFACE_PROBE_TARGET_CHALLENGE_COOKIE_TOKENS,
    BROWSER_SURFACE_PROBE_TARGET_COOKIE_NAME_LIMIT,
    BROWSER_SURFACE_PROBE_TARGET_GEO_ENDPOINTS,
    BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS,
    BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS,
    BROWSER_SURFACE_PROBE_TARGET_RESPONSE_HEADER_ALLOWLIST,
    BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT,
)
from browser_surface_probe.signal_extractor import (
    _collect_baseline,
    _collect_behavioral_smoke,
    _collect_page_snapshot,
)
from browser_surface_probe.value_coercion import (
    coalesce as _coalesce,
    country_code_from_value as _country_code_from_value,
    locale_region as _locale_region,
    object_dict as _object_dict,
    object_list as _object_list,
    dedupe as _dedupe,
    normalize_space as _normalize_space,
    timezone_matches_country as _timezone_matches_country,
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class RuntimeSource:
    source_kind: str
    run_id: int | None
    identity_run_id: int
    proxy_list: list[str]
    proxy_profile: dict[str, object]
    locality_profile: dict[str, object]
    selected_proxy: str | None
    selected_proxy_index: int | None
    browser_engine: str


__all__ = [
    "_target_identity_mismatch",
    "_target_root_cause",
]


def _target_identity_mismatch(
    *,
    locale: str,
    timezone_name: str,
    geo_country_code: str | None,
) -> dict[str, object]:
    locale_region = _locale_region(locale)
    timezone_match = _timezone_matches_country(timezone_name, geo_country_code)
    return {
        "geo_country_code": geo_country_code,
        "locale_region": locale_region,
        "locale_country_match": (
            locale_region == geo_country_code
            if locale_region and geo_country_code
            else None
        ),
        "timezone_country_match": timezone_match,
    }


def _target_vendor(
    browser: dict[str, object], transport_payloads: list[dict[str, object]]
) -> object:
    browser_classification = _object_dict(browser.get("classification"))
    header_vendors = [
        _object_dict(payload.get("classification")).get("header_vendor")
        for payload in transport_payloads
    ]
    provider_hits = [
        _coalesce(
            _object_list(
                _object_dict(payload.get("classification")).get("provider_hits")
            )
        )
        for payload in [browser, *transport_payloads]
    ]
    return (
        browser_classification.get("header_vendor")
        or _coalesce(header_vendors)
        or _coalesce(provider_hits)
    )


def _target_path_flags(
    browser: dict[str, object], transport_payloads: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]], bool, bool]:
    transport_blocked = [
        payload
        for payload in transport_payloads
        if payload.get("status") == "ok" and bool(payload.get("blocked"))
    ]
    transport_ok = [
        payload
        for payload in transport_payloads
        if payload.get("status") == "ok" and not bool(payload.get("blocked"))
    ]
    browser_blocked = browser.get("status") == "ok" and bool(browser.get("blocked"))
    browser_ok = browser.get("status") == "ok" and not bool(browser.get("blocked"))
    return transport_blocked, transport_ok, browser_blocked, browser_ok


def _geo_identity_drifts(mismatch: dict[str, object]) -> bool:
    return (
        mismatch.get("timezone_country_match") is False
        or mismatch.get("locale_country_match") is False
    )


def _target_root_cause(
    *,
    consensus: dict[str, object],
    diagnostic: dict[str, object],
) -> dict[str, object]:
    geo = _object_dict(_object_dict(diagnostic.get("geo")).get("consensus"))
    geo_country = _country_code_from_value(str(geo.get("country") or ""))
    mismatch = _target_identity_mismatch(
        locale=str(consensus.get("locale") or ""),
        timezone_name=str(consensus.get("timezone") or ""),
        geo_country_code=geo_country,
    )
    transport_payloads = [
        _object_dict(diagnostic.get("httpx")),
        _object_dict(diagnostic.get("curl_cffi")),
    ]
    browser = _object_dict(diagnostic.get("browser"))
    transport_blocked, transport_ok, browser_blocked, browser_ok = _target_path_flags(
        browser, transport_payloads
    )
    browser_classification = _object_dict(browser.get("classification"))
    vendor = _target_vendor(browser, transport_payloads)
    if transport_blocked and browser_blocked:
        return {
            "category": "target_precontent_block",
            "confidence": "high",
            "message": "HTTP and browser paths both blocked before usable content.",
            "evidence": {
                "vendor": vendor,
                "geo_identity": mismatch,
                "httpx": {
                    "status_code": transport_payloads[0].get("status_code"),
                    "outcome": _object_dict(
                        transport_payloads[0].get("classification")
                    ).get("outcome"),
                },
                "curl_cffi": {
                    "status_code": transport_payloads[1].get("status_code"),
                    "outcome": _object_dict(
                        transport_payloads[1].get("classification")
                    ).get("outcome"),
                },
                "browser": {
                    "status_code": browser.get("status_code"),
                    "outcome": browser_classification.get("outcome"),
                    "challenge_cookie_names": browser.get("challenge_cookie_names"),
                },
            },
        }
    if browser_blocked and transport_ok:
        if _geo_identity_drifts(mismatch):
            return {
                "category": "browser_geo_identity_mismatch",
                "confidence": "high",
                "message": "Browser path blocked while transport passes and browser geo identity drifts from observed egress country.",
                "evidence": {
                    "geo_identity": mismatch,
                    "browser": {
                        "status_code": browser.get("status_code"),
                        "outcome": browser_classification.get("outcome"),
                    },
                },
            }
        return {
            "category": "browser_session_or_fingerprint_block",
            "confidence": "high",
            "message": "Browser path blocked while transport passes; failure is browser session or browser-only fingerprint flow.",
            "evidence": {
                "vendor": vendor,
                "browser": {
                    "status_code": browser.get("status_code"),
                    "outcome": browser_classification.get("outcome"),
                    "challenge_cookie_names": browser.get("challenge_cookie_names"),
                },
            },
        }
    if browser_ok and transport_blocked:
        return {
            "category": "transport_only_block",
            "confidence": "high",
            "message": "Transport paths blocked while browser path stays usable.",
            "evidence": {
                "vendor": vendor,
                "httpx_status_code": transport_payloads[0].get("status_code"),
                "curl_status_code": transport_payloads[1].get("status_code"),
            },
        }
    if browser_ok or transport_ok:
        return {
            "category": "no_target_block_detected",
            "confidence": "high",
            "message": "At least one acquisition path reached usable content.",
            "evidence": {
                "geo_identity": mismatch,
            },
        }
    return {
        "category": "target_diagnostic_inconclusive",
        "confidence": "low",
        "message": "Target diagnostics did not produce enough successful paths to classify the failure mechanically.",
        "evidence": {
            "geo_identity": mismatch,
            "browser_status": browser.get("status"),
            "httpx_status": transport_payloads[0].get("status"),
            "curl_status": transport_payloads[1].get("status"),
        },
    }


def _slugify(value: object) -> str:
    normalized = _NON_ALNUM_RE.sub("-", _normalize_space(value).lower()).strip("-")
    return normalized or "target"


def _validated_target_url(value: object) -> str:
    url = _normalize_space(value)
    parsed = urlparse(url)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme not in {"http", "https"}:
        raise ValueError("target URL must use http or https")
    if not parsed.hostname:
        raise ValueError("target URL must include a hostname")
    host = str(parsed.hostname).strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("target URL host must not be local")
    addresses: list[IPv4Address | IPv6Address] = []
    try:
        addresses.append(ip_address(host))
    except ValueError:
        try:
            addresses.extend(
                ip_address(row[4][0])
                for row in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            )
        except (OSError, ValueError) as exc:
            raise ValueError("target URL hostname could not be resolved") from exc
    if not addresses or any(_address_is_local(address) for address in addresses):
        raise ValueError("target URL host must not be local or private")
    return url


def _address_is_local(address: IPv4Address | IPv6Address) -> bool:
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _truncate_text(value: object, *, limit: int) -> str:
    normalized = _normalize_space(value)
    return normalized[:limit] if limit > 0 else normalized


def _failed_target_diagnostic(*, url: str, error: str) -> dict[str, object]:
    parsed = urlparse(url)
    host = _normalize_space(parsed.netloc or parsed.path)
    return {
        "target_id": _slugify(host or url),
        "url": url,
        "host": host,
        "geo": {},
        "httpx": {"status": "failed", "error": error},
        "curl_cffi": {"status": "failed", "error": error},
        "browser": {"status": "failed", "error": error},
    }


def _text_snippet_from_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(html or ""))
    text = _normalize_space(text)
    return _truncate_text(
        text, limit=int(BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT)
    )


def _target_artifacts(base_dir: Path, target_id: str, variant: str) -> dict[str, Path]:
    return {
        "body": base_dir / f"{target_id}_{variant}.txt",
        "html": base_dir / f"{target_id}_{variant}.html",
        "screenshot": base_dir / f"{target_id}_{variant}.png",
    }


def _write_target_body_artifact(path: Path, body: str) -> None:
    path.write_text(
        str(body or "")[: int(BROWSER_SURFACE_PROBE_TARGET_BODY_ARTIFACT_LIMIT)],
        encoding="utf-8",
    )


def _selected_headers(headers: Any) -> dict[str, str]:
    normalized = copy_headers(headers)
    allowlist = {
        str(value).strip().lower()
        for value in BROWSER_SURFACE_PROBE_TARGET_RESPONSE_HEADER_ALLOWLIST
    }
    selected: dict[str, str] = {}
    for key, value in normalized.multi_items():
        lowered = str(key or "").strip().lower()
        if lowered not in allowlist:
            continue
        if lowered == "set-cookie":
            selected.setdefault(lowered, value)
            continue
        selected[lowered] = value
    return selected


def _classification_payload(
    *, html: str, status_code: int, headers: Any
) -> dict[str, object]:
    classification = classify_blocked_page(html, status_code)
    return {
        "blocked": bool(classification.blocked),
        "outcome": classification.outcome,
        "evidence": list(classification.evidence),
        "provider_hits": list(classification.provider_hits),
        "active_provider_hits": list(classification.active_provider_hits),
        "strong_hits": list(classification.strong_hits),
        "weak_hits": list(classification.weak_hits),
        "title_matches": list(classification.title_matches),
        "challenge_element_hits": list(classification.challenge_element_hits),
        "header_vendor": classify_block_from_headers(headers),
    }


def _geo_payload_from_text(text: str) -> dict[str, object]:
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    timezone = payload.get("timezone")
    if isinstance(timezone, dict):
        timezone = timezone.get("id") or timezone.get("name")
    connection = payload.get("connection")
    connection = dict(connection) if isinstance(connection, dict) else {}
    return {
        "ip": _normalize_space(payload.get("ip")),
        "city": _normalize_space(payload.get("city")),
        "region": _normalize_space(payload.get("region") or payload.get("regionName")),
        "country": _normalize_space(
            payload.get("country")
            or payload.get("country_code")
            or payload.get("country_name")
        ),
        "timezone": _normalize_space(timezone),
        "org": _normalize_space(
            payload.get("org") or payload.get("isp") or connection.get("org")
        ),
        "raw": payload,
    }


def _geo_consensus(results: list[dict[str, object]]) -> dict[str, object]:
    keys = ("ip", "city", "region", "country", "timezone", "org")
    consensus: dict[str, object] = {}
    for key in keys:
        consensus[key] = _coalesce([result.get(key) for result in results])
    return consensus


async def _run_geo_endpoint_checks(proxy: str | None) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for endpoint in BROWSER_SURFACE_PROBE_TARGET_GEO_ENDPOINTS:
        url = str(endpoint.get("url") or "").strip()
        label = str(endpoint.get("label") or endpoint.get("id") or url).strip()
        if not url:
            continue
        for method_name, fetcher in (("httpx", http_fetch), ("curl_cffi", curl_fetch)):
            try:
                result = await fetcher(
                    url,
                    float(BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS),
                    proxy=proxy,
                )
                payload = _geo_payload_from_text(result.html)
                checks.append(
                    {
                        "label": label,
                        "method": method_name,
                        "url": url,
                        "status_code": result.status_code,
                        "final_url": result.final_url,
                        "geo": payload,
                    }
                )
            except Exception as exc:
                checks.append(
                    {
                        "label": label,
                        "method": method_name,
                        "url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                        "geo": {},
                    }
                )
    return {
        "checks": checks,
        "consensus": _geo_consensus(
            [
                geo_payload
                for check in checks
                if (geo_payload := _object_dict(check.get("geo")))
            ]
        ),
    }


async def _target_transport_payload(
    *,
    method_label: str,
    fetcher,
    url: str,
    proxy: str | None,
    artifacts_dir: Path,
    target_id: str,
) -> dict[str, object]:
    artifacts = _target_artifacts(artifacts_dir, target_id, method_label)
    try:
        result = await fetcher(
            url,
            float(BROWSER_SURFACE_PROBE_TARGET_HTTP_TIMEOUT_SECONDS),
            proxy=proxy,
        )
    except Exception as exc:
        return {
            "method": method_label,
            "url": url,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": {"body": None, "html": None, "screenshot": None},
        }
    _write_target_body_artifact(artifacts["body"], result.html)
    if "html" in str(result.content_type or "").lower():
        artifacts["html"].write_text(result.html, encoding="utf-8")
        html_name = artifacts["html"].name
    else:
        html_name = None
    return {
        "method": method_label,
        "url": url,
        "status": "ok",
        "status_code": result.status_code,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "blocked": bool(result.blocked),
        "classification": _classification_payload(
            html=result.html,
            status_code=result.status_code,
            headers=result.headers,
        ),
        "response_headers": _selected_headers(result.headers),
        "visible_text_snippet": _text_snippet_from_html(result.html),
        "artifacts": {
            "body": artifacts["body"].name,
            "html": html_name,
            "screenshot": None,
        },
    }


async def _response_headers_dict(response: object | None) -> dict[str, str]:
    if response is None:
        return {}
    for attr in ("all_headers", "headers"):
        candidate = getattr(response, attr, None)
        if candidate is None:
            continue
        try:
            resolved = await candidate() if callable(candidate) else candidate
        except TypeError:
            try:
                resolved = candidate()
            except Exception:
                continue
        except Exception:
            continue
        if isinstance(resolved, dict):
            return {str(key): str(value) for key, value in resolved.items()}
    return {}


async def _browser_cookie_names(page: Any, final_url: str) -> list[str]:
    context = getattr(page, "context", None)
    if context is None:
        return []
    cookies_method = getattr(context, "cookies", None)
    if cookies_method is None:
        return []
    try:
        cookies = await cookies_method([final_url]) if callable(cookies_method) else []
    except Exception:
        return []
    names = [
        _normalize_space(cookie.get("name"))
        for cookie in cookies
        if isinstance(cookie, dict) and _normalize_space(cookie.get("name"))
    ]
    return _dedupe(names)[: int(BROWSER_SURFACE_PROBE_TARGET_COOKIE_NAME_LIMIT)]


def _challenge_cookie_names(cookie_names: list[str]) -> list[str]:
    tokens = tuple(
        str(token).strip().lower()
        for token in BROWSER_SURFACE_PROBE_TARGET_CHALLENGE_COOKIE_TOKENS
    )
    return [
        name
        for name in cookie_names
        if any(token and token in name.lower() for token in tokens)
    ]


async def _target_browser_payload(
    runtime: SharedBrowserRuntime,
    *,
    url: str,
    run_id: int,
    locality_profile: dict[str, object],
    artifacts_dir: Path,
    target_id: str,
) -> dict[str, object]:
    artifacts = _target_artifacts(artifacts_dir, target_id, "browser")
    async with runtime.page(
        run_id=run_id,
        locality_profile=locality_profile,
        allow_storage_state=False,
    ) as page:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS),
        )
        for state, timeout_ms in (("load", 10000), ("networkidle", 8000)):
            try:
                await page.wait_for_load_state(state, timeout=timeout_ms)
            except Exception:
                continue
        await page.wait_for_timeout(int(BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS))
        html = await page.content()
        snapshot = await _collect_page_snapshot(page)
        behavioral_smoke = await _collect_behavioral_smoke(page)
        baseline = await _collect_baseline(page, behavioral_smoke=behavioral_smoke)
        await page.screenshot(path=str(artifacts["screenshot"]), full_page=True)
        artifacts["html"].write_text(html, encoding="utf-8")
        _write_target_body_artifact(artifacts["body"], html)
        final_url = _normalize_space(page.url)
        response_headers = await _response_headers_dict(response)
        status_code = 0
        if response is not None:
            status_attr = getattr(response, "status", None)
            try:
                status_code = int(
                    status_attr() if callable(status_attr) else status_attr or 0
                )
            except Exception:
                status_code = 0
        cookie_names = await _browser_cookie_names(page, final_url or url)
        return {
            "method": "browser",
            "url": url,
            "status": "ok",
            "status_code": status_code,
            "final_url": final_url,
            "title": _normalize_space(await page.title()),
            "blocked": bool(classify_blocked_page(html, status_code).blocked),
            "classification": _classification_payload(
                html=html,
                status_code=status_code,
                headers=response_headers,
            ),
            "response_headers": _selected_headers(response_headers),
            "baseline": baseline,
            "snapshot_summary": {
                "line_count": snapshot.get("line_count", 0),
                "line_count_raw": snapshot.get(
                    "line_count_raw", snapshot.get("line_count", 0)
                ),
                "lines": _object_list(snapshot.get("lines")),
            },
            "visible_text_snippet": _truncate_text(
                " ".join(
                    str(line) for line in _object_list(snapshot.get("lines"))[:12]
                ),
                limit=int(BROWSER_SURFACE_PROBE_TARGET_VISIBLE_TEXT_SNIPPET_LIMIT),
            ),
            "cookie_names": cookie_names,
            "challenge_cookie_names": _challenge_cookie_names(cookie_names),
            "artifacts": {
                "body": artifacts["body"].name,
                "html": artifacts["html"].name,
                "screenshot": artifacts["screenshot"].name,
            },
        }


async def _run_target_diagnostic(
    runtime: SharedBrowserRuntime,
    *,
    url: str,
    runtime_source: RuntimeSource,
    artifacts_dir: Path,
) -> dict[str, object]:
    url = _validated_target_url(url)
    parsed = urlparse(url)
    host = _normalize_space(parsed.netloc or parsed.path)
    target_id = _slugify(host)
    geo = await _run_geo_endpoint_checks(runtime_source.selected_proxy)
    transport_http = await _target_transport_payload(
        method_label="httpx",
        fetcher=http_fetch,
        url=url,
        proxy=runtime_source.selected_proxy,
        artifacts_dir=artifacts_dir,
        target_id=target_id,
    )
    transport_curl = await _target_transport_payload(
        method_label="curl_cffi",
        fetcher=curl_fetch,
        url=url,
        proxy=runtime_source.selected_proxy,
        artifacts_dir=artifacts_dir,
        target_id=target_id,
    )
    try:
        browser_payload = await _target_browser_payload(
            runtime,
            url=url,
            run_id=runtime_source.identity_run_id,
            locality_profile=runtime_source.locality_profile,
            artifacts_dir=artifacts_dir,
            target_id=target_id,
        )
    except Exception as exc:
        browser_payload = {
            "method": "browser",
            "url": url,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "artifacts": {"body": None, "html": None, "screenshot": None},
        }
    return {
        "target_id": target_id,
        "url": url,
        "host": host,
        "geo": geo,
        "httpx": transport_http,
        "curl_cffi": transport_curl,
        "browser": browser_payload,
    }


async def _navigate_probe_target(page, url: str) -> None:
    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=int(BROWSER_SURFACE_PROBE_TARGET_NAVIGATION_TIMEOUT_MS),
    )
    for state, timeout_ms in (("load", 10000), ("networkidle", 8000)):
        try:
            await page.wait_for_load_state(state, timeout=timeout_ms)
        except Exception:
            continue
    await page.wait_for_timeout(int(BROWSER_SURFACE_PROBE_POST_NAVIGATION_WAIT_MS))


async def _capture_probe_artifacts(page, artifacts: dict[str, Path]) -> None:
    try:
        await page.screenshot(path=str(artifacts["screenshot"]), full_page=True)
    except Exception:
        # Screenshot artifact is diagnostic-only; ignore capture failures.
        pass
    try:
        artifacts["html"].write_text(await page.content(), encoding="utf-8")
    except Exception:
        # HTML artifact is diagnostic-only; ignore capture failures.
        pass
