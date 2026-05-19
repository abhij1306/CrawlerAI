from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.dom.xpath_service import extract_selector_value
from app.services.field_policy import normalize_field_key
from app.services.selectors_runtime import create_selector_record, list_selector_records


async def auto_save_dom_observed_selectors(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    html: str,
    records: list[dict[str, object]],
    source_run_id: int | None,
) -> list[dict[str, object]]:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_domain or not normalized_surface:
        return []
    candidates = _dom_observed_selector_candidates(
        records,
        source_run_id=source_run_id,
    )
    if not candidates:
        return []
    existing_rows = await list_selector_records(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    protected_fields = {
        str(row.get("field_name") or "").strip().lower()
        for row in existing_rows
        if bool(row.get("is_active", True))
        and str(row.get("source") or "").strip() not in {"dom_observed", ""}
    }
    existing_signatures = {_selector_signature(row) for row in existing_rows}
    saved_rows: list[dict[str, object]] = []
    for candidate in candidates:
        field_name = str(candidate.get("field_name") or "").strip().lower()
        if not field_name or field_name in protected_fields:
            continue
        signature = _selector_signature(candidate)
        if signature in existing_signatures:
            continue
        if not _dom_observed_selector_still_matches(html, candidate):
            continue
        saved = await create_selector_record(
            session,
            domain=normalized_domain,
            surface=normalized_surface,
            payload=candidate,
            commit=False,
        )
        saved_rows.append(saved)
        existing_signatures.add(signature)
    if saved_rows:
        await session.flush()
    return saved_rows


def _dom_observed_selector_candidates(
    records: list[dict[str, object]],
    *,
    source_run_id: int | None,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for trace_map_key in ("_selector_traces", "_dom_observed_selector_traces"):
            selector_traces = record.get(trace_map_key)
            if not isinstance(selector_traces, dict):
                continue
            for field_name, trace in selector_traces.items():
                candidate = _candidate_from_trace(
                    field_name,
                    trace,
                    source_run_id=source_run_id,
                )
                if candidate is None:
                    continue
                signature = _selector_signature(candidate)
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append(candidate)
    return candidates


def _candidate_from_trace(
    field_name: object,
    trace: object,
    *,
    source_run_id: int | None,
) -> dict[str, object] | None:
    if not isinstance(trace, dict):
        return None
    if str(trace.get("selector_source") or "").strip() != "dom_observed":
        return None
    normalized_field = normalize_field_key(str(field_name or ""))
    selector_kind = str(trace.get("selector_kind") or "").strip()
    selector_value = str(trace.get("selector_value") or "").strip()
    if not normalized_field or not selector_kind or not selector_value:
        return None
    return {
        "field_name": normalized_field,
        "css_selector": selector_value if selector_kind == "css_selector" else None,
        "xpath": selector_value if selector_kind == "xpath" else None,
        "regex": selector_value if selector_kind == "regex" else None,
        "sample_value": str(trace.get("sample_value") or "").strip() or None,
        "source": "dom_observed",
        "source_run_id": source_run_id,
        "status": "validated",
        "is_active": True,
    }


def _dom_observed_selector_still_matches(
    html: str,
    candidate: dict[str, object],
) -> bool:
    matched_value, count, _selector_used = extract_selector_value(
        html,
        css_selector=str(candidate.get("css_selector") or "").strip() or None,
        xpath=str(candidate.get("xpath") or "").strip() or None,
        regex=str(candidate.get("regex") or "").strip() or None,
    )
    if count <= 0 or matched_value in (None, ""):
        return False
    candidate["sample_value"] = str(matched_value)
    return True


def _selector_signature(row: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("field_name") or "").strip().lower(),
        str(row.get("css_selector") or "").strip(),
        str(row.get("xpath") or "").strip(),
        str(row.get("regex") or "").strip(),
    )
