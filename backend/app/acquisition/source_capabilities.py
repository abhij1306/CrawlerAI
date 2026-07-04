from __future__ import annotations

from typing import Any, Protocol

from app.core.config.extraction_rules import DETAIL_TERMINAL_SOURCE_UNAVAILABLE_OUTCOMES
from app.core.records.detail_outcome import normalized_detail_outcome

PRODUCT_DATA_ENDPOINT_TYPES = frozenset({"product_api", "graphql"})
OFFER_FIELD_FAMILIES = ("price", "currency", "availability")
VARIANT_FIELD_FAMILIES = ("variants",)
DETAIL_FIELD_FAMILIES = (
    "title",
    "brand",
    "description",
    "sku",
    "price",
    "currency",
    "availability",
    "image_url",
    "images",
    "variants",
)


class AcquisitionResultLike(Protocol):
    html: str
    status_code: int
    blocked: bool
    network_payloads: list[dict[str, object]]
    browser_diagnostics: dict[str, object]
    acquisition_diagnostics: dict[str, object]


def build_source_capability_diagnostics(
    *,
    html: str,
    network_payloads: list[dict[str, object]],
    browser_diagnostics: dict[str, object] | None = None,
    status_code: int | None = None,
    browser_outcome: str | None = None,
    blocked: bool = False,
) -> dict[str, object]:
    text = str(html or "")
    lower = text.casefold()
    structured_present = any(
        marker in lower
        for marker in (
            'type="application/ld+json"',
            "type='application/ld+json'",
            "__next_data__",
            "__nuxt__",
            "window.__initial_state__",
        )
    )

    observed: list[dict[str, object]] = []
    failed: list[dict[str, object]] = []
    succeeded: list[dict[str, object]] = []
    for payload in network_payloads:
        endpoint_type = str(payload.get("endpoint_type") or "")
        if endpoint_type not in PRODUCT_DATA_ENDPOINT_TYPES:
            continue
        status = payload.get("status")
        row = {
            "endpoint_type": endpoint_type,
            "status": status,
            "url": payload.get("url") or payload.get("request_url"),
        }
        observed.append(row)
        if isinstance(status, int) and 200 <= status < 400:
            succeeded.append(row)
        elif isinstance(status, int) and status >= 400:
            failed.append(row)

    shell_outcome = str(browser_outcome or "").strip().casefold()
    http_error = isinstance(status_code, int) and status_code >= 400
    detail_outcome = normalized_detail_outcome(
        http_status=status_code,
        blocked=blocked,
        browser_outcome=shell_outcome,
    )
    terminal_shell = bool(
        blocked or shell_outcome in {"challenge_page", "low_content_shell"}
    )
    terminal_detail_unavailable = (
        detail_outcome in DETAIL_TERMINAL_SOURCE_UNAVAILABLE_OUTCOMES
    )
    product_source_unavailable = bool(
        http_error
        or (observed and failed and not succeeded)
        or terminal_detail_unavailable
    )
    browser = browser_diagnostics or {}
    interaction_present = bool(
        browser.get("detail_expansion_attempted")
        or browser.get("variant_controls_detected")
        or browser.get("interaction_required")
    )

    affected_fields: list[str] = []
    if terminal_detail_unavailable:
        affected_fields.extend(DETAIL_FIELD_FAMILIES)
    elif product_source_unavailable:
        affected_fields.extend(OFFER_FIELD_FAMILIES)
        affected_fields.extend(VARIANT_FIELD_FAMILIES)

    return {
        "html_present": bool(text.strip()),
        "structured_data_present": structured_present,
        "product_data_source_observed": bool(observed),
        "product_data_source_succeeded": bool(succeeded),
        "product_data_source_unavailable": product_source_unavailable,
        "terminal_shell": terminal_shell,
        "detail_outcome": detail_outcome,
        "status_code": status_code,
        "browser_outcome": shell_outcome or None,
        "interaction_controls_present": interaction_present,
        "affected_field_families": tuple(dict.fromkeys(affected_fields)),
        "observed_product_sources": tuple(observed),
        "failed_product_sources": tuple(failed),
    }


def attach_source_capability_diagnostics(result: AcquisitionResultLike | Any) -> None:
    diagnostics = dict(result.acquisition_diagnostics or {})
    browser_diagnostics = dict(result.browser_diagnostics or {})
    diagnostics["source_capabilities"] = build_source_capability_diagnostics(
        html=str(result.html or ""),
        network_payloads=list(result.network_payloads or []),
        browser_diagnostics=browser_diagnostics,
        status_code=getattr(result, "status_code", None),
        browser_outcome=browser_diagnostics.get("browser_outcome"),
        blocked=bool(getattr(result, "blocked", False)),
    )
    result.acquisition_diagnostics = diagnostics
