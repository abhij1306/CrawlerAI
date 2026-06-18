from __future__ import annotations

from typing import Any

from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.js_state.helpers import compact_dict
from app.services.platform_policy import platform_js_state_extractors

__all__ = [
    "map_configured_state_payload",
    "map_job_detail_state",
    "path_value",
]


def map_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    mapped = _map_platform_job_detail_state(js_state_objects)
    if not mapped:
        return {}
    description_html = str(mapped.pop("description_html", "") or "").strip()
    if description_html:
        mapped.update(extract_job_sections(description_html))
        if "description" not in mapped:
            mapped["description"] = html_to_text(description_html)
    if mapped.get("apply_url") and not mapped.get("url"):
        mapped["url"] = mapped["apply_url"]
    return mapped


def _map_platform_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    for state_key, payload in js_state_objects.items():
        if not isinstance(payload, dict):
            continue
        extractors = platform_js_state_extractors(
            surface="job_detail",
            state_key=state_key,
        )
        for extractor in extractors:
            mapped = map_configured_state_payload(
                payload,
                root_paths=extractor.root_paths.get(state_key, []),
                field_paths=extractor.field_paths,
            )
            if mapped:
                return mapped
    return {}


def map_configured_state_payload(
    payload: dict[str, Any],
    *,
    root_paths: list[list[str]],
    field_paths: dict[str, list[list[str]]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for root_path in root_paths:
        candidate = path_value(payload, root_path)
        if not isinstance(candidate, dict):
            continue
        mapped = compact_dict(
            {
                field_name: _first_path_value(candidate, paths)
                for field_name, paths in field_paths.items()
            }
        )
        for field_name, value in mapped.items():
            if merged.get(field_name) in (None, "", [], {}) and value not in (
                None,
                "",
                [],
                {},
            ):
                merged[field_name] = value
    return compact_dict(merged)


def _first_path_value(payload: dict[str, Any], paths: list[list[str]]) -> Any:
    for path in paths:
        value = path_value(payload, path)
        if value not in (None, "", [], {}):
            return value
    return None


def path_value(payload: Any, path: list[str]) -> Any:
    current = payload
    for segment in path:
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list):
            try:
                current = current[int(segment)]
            except (TypeError, ValueError, IndexError):
                return None
            continue
        return None
    return current
