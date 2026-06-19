from __future__ import annotations

from app.services.extraction import (
    extract,
    parse_surface,
)
from app.services.extraction.replay import request_from_inputs


def extract_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
    requested_fields: list[str] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
    content_type: str | None = None,
    browser_diagnostics: dict[str, object] | None = None,
    record_dom_observed_selectors: bool = False,
) -> list[dict]:
    del (
        extraction_runtime_snapshot,
        content_type,
        browser_diagnostics,
        record_dom_observed_selectors,
    )
    normalized_surface = parse_surface(surface)
    request = request_from_inputs(
        normalized_surface,
        html,
        page_url,
        requested_url=requested_page_url,
        max_records=max_records,
        requested_fields=tuple(str(field) for field in requested_fields or ()),
        network_payloads=network_payloads,
        artifacts={
            **dict(artifacts or {}),
            "css_field_rules": list(selector_rules or []),
        },
    )
    result = extract(request)
    if artifacts is not None:
        artifacts["extraction_replay"] = (
            result.replay
            if isinstance(result.replay, dict)
            else result.model_dump(mode="json")
        )
    return list(result.records)
