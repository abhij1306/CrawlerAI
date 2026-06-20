from __future__ import annotations

from app.core.config.browser_fingerprint_profiles import BROWSER_REQUIRED_REASONS
from app.core.db_utils import mapping_or_empty
from app.core.shared.field_coerce import object_list as _object_list
from app.core.shared.field_coerce import safe_int as _safe_int
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.domain_memory import DomainFieldFeedback


def selector_signature(
    *,
    field_name: object,
    selector_kind: object,
    selector_value: object,
) -> tuple[str, str, str]:
    return (
        str(field_name or "").strip().lower(),
        str(selector_kind or "").strip().lower(),
        str(selector_value or "").strip(),
    )


def saved_selector_signature(row: dict[str, object]) -> tuple[str, str, str]:
    return selector_signature(
        field_name=row.get("field_name"),
        selector_kind="css_selector",
        selector_value=row.get("css_selector"),
    )


def derive_acquisition_info(
    records: list[CrawlRecord],
    *,
    run: CrawlRun,
) -> dict[str, object]:
    browser_required = False
    actual_fetch_method: str | None = None
    browser_reason: str | None = None
    affordance_candidates: dict[str, object] = {
        "accordions": [],
        "tabs": [],
        "carousels": [],
        "shadow_hosts": [],
        "iframe_promotion": None,
        "browser_required": False,
    }
    for record in records:
        source_trace = mapping_or_empty(record.source_trace)
        acquisition = mapping_or_empty(source_trace.get("acquisition"))
        browser_diagnostics = mapping_or_empty(acquisition.get("browser_diagnostics"))
        if actual_fetch_method is None:
            method = str(acquisition.get("method") or "").strip()
            if method:
                actual_fetch_method = method
        if browser_reason is None:
            next_browser_reason = (
                str(browser_diagnostics.get("browser_reason") or "").strip().lower()
            )
            if next_browser_reason:
                browser_reason = next_browser_reason
        if (
            str(acquisition.get("method") or "").strip().lower() == "browser"
            and str(browser_diagnostics.get("browser_reason") or "").strip().lower()
            in BROWSER_REQUIRED_REASONS
        ):
            browser_required = True
        _merge_affordance_candidates(
            affordance_candidates,
            acquisition=acquisition,
            browser_diagnostics=browser_diagnostics,
        )
    acquisition_summary = mapping_or_empty(
        mapping_or_empty(run.result_summary).get("acquisition_summary")
    )
    if actual_fetch_method is None and mapping_or_empty(
        acquisition_summary.get("methods")
    ).get("browser"):
        actual_fetch_method = "browser"
    if browser_reason is None and actual_fetch_method == "browser":
        browser_reason = "http-escalation"
    affordance_candidates["browser_required"] = browser_required
    return {
        "actual_fetch_method": actual_fetch_method,
        "browser_required": browser_required,
        "browser_reason": browser_reason,
        "acquisition_summary": acquisition_summary,
        "affordance_candidates": affordance_candidates,
    }


def collect_selector_candidates(
    records: list[CrawlRecord],
    *,
    saved_selectors: list[dict[str, object]],
    run: CrawlRun,
    feedback_index: dict[tuple[str, str, str], DomainFieldFeedback],
) -> tuple[dict[str, dict[str, object]], dict[tuple[str, str, str], dict[str, object]]]:
    saved_selector_index = {
        saved_selector_signature(row): row for row in saved_selectors
    }
    selector_candidates: dict[str, dict[str, object]] = {}
    field_learning: dict[tuple[str, str, str], dict[str, object]] = {}
    for record in records:
        _collect_record_selector_candidates(
            record,
            run=run,
            saved_selector_index=saved_selector_index,
            feedback_index=feedback_index,
            selector_candidates=selector_candidates,
            field_learning=field_learning,
        )
    if selector_candidates:
        return selector_candidates, field_learning
    _collect_fallback_selector_candidates(
        saved_selectors,
        run=run,
        saved_selector_index=saved_selector_index,
        selector_candidates=selector_candidates,
    )
    return selector_candidates, field_learning


def _collect_record_selector_candidates(
    record: CrawlRecord,
    *,
    run: CrawlRun,
    saved_selector_index: dict[tuple[str, str, str], dict[str, object]],
    feedback_index: dict[tuple[str, str, str], DomainFieldFeedback],
    selector_candidates: dict[str, dict[str, object]],
    field_learning: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    source_trace = mapping_or_empty(record.source_trace)
    field_discovery = mapping_or_empty(source_trace.get("field_discovery"))
    for field_name, payload in field_discovery.items():
        payload_map = payload if isinstance(payload, dict) else {}
        selector_trace = mapping_or_empty(payload_map.get("selector_trace"))
        selector_kind = str(selector_trace.get("selector_kind") or "").strip()
        selector_value = str(selector_trace.get("selector_value") or "").strip()
        source_labels = [
            str(value)
            for value in payload_map.get("sources") or []
            if str(value or "").strip()
        ]
        _collect_field_learning(
            record,
            field_name=field_name,
            payload_map=payload_map,
            selector_kind=selector_kind,
            selector_value=selector_value,
            source_labels=source_labels,
            feedback_index=feedback_index,
            field_learning=field_learning,
        )
        if not selector_kind or not selector_value:
            continue
        _collect_selector_candidate(
            record,
            run=run,
            field_name=field_name,
            payload_map=payload_map,
            selector_trace=selector_trace,
            selector_kind=selector_kind,
            selector_value=selector_value,
            saved_selector_index=saved_selector_index,
            selector_candidates=selector_candidates,
        )


def _collect_field_learning(
    record: CrawlRecord,
    *,
    field_name: object,
    payload_map: dict[str, object],
    selector_kind: str,
    selector_value: str,
    source_labels: list[str],
    feedback_index: dict[tuple[str, str, str], DomainFieldFeedback],
    field_learning: dict[tuple[str, str, str], dict[str, object]],
) -> None:
    if not (
        payload_map.get("status") == "found"
        and payload_map.get("value") not in (None, "", [], {})
        and selector_kind == "css_selector"
        and selector_value
    ):
        return
    learning_key = (
        str(field_name or "").strip().lower(),
        selector_kind,
        selector_value or (source_labels[-1] if source_labels else ""),
    )
    feedback_row = feedback_index.get(learning_key)
    learning_entry = field_learning.setdefault(
        learning_key,
        {
            "field_name": str(field_name or "").strip().lower(),
            "value": payload_map.get("value"),
            "source_labels": source_labels,
            "selector_kind": selector_kind or None,
            "selector_value": selector_value or None,
            "source_record_ids": [],
            "feedback": (
                _serialize_feedback_row(feedback_row)
                if feedback_row is not None
                else None
            ),
        },
    )
    learning_entry["source_record_ids"] = sorted(
        {
            parsed
            for value in [
                *_object_list(learning_entry.get("source_record_ids")),
                record.id,
            ]
            if (parsed := _safe_int(value)) is not None
        }
    )


def _collect_selector_candidate(
    record: CrawlRecord,
    *,
    run: CrawlRun,
    field_name: object,
    payload_map: dict[str, object],
    selector_trace: dict[str, object],
    selector_kind: str,
    selector_value: str,
    saved_selector_index: dict[tuple[str, str, str], dict[str, object]],
    selector_candidates: dict[str, dict[str, object]],
) -> None:
    candidate_key = f"{field_name}|{selector_kind}|{selector_value}"
    saved_selector = saved_selector_index.get(
        selector_signature(
            field_name=field_name,
            selector_kind=selector_kind,
            selector_value=selector_value,
        )
    )
    entry = selector_candidates.setdefault(
        candidate_key,
        {
            "candidate_key": candidate_key,
            "field_name": str(field_name or "").strip().lower(),
            "selector_kind": selector_kind,
            "selector_value": selector_value,
            "selector_source": str(selector_trace.get("selector_source") or ""),
            "sample_value": selector_trace.get("sample_value")
            or payload_map.get("value"),
            "source_record_ids": [],
            "source_run_id": selector_trace.get("source_run_id") or run.id,
            "saved_selector_id": saved_selector.get("id")
            if isinstance(saved_selector, dict)
            else None,
            "already_saved": isinstance(saved_selector, dict),
            "final_field_source": (
                _object_list(payload_map.get("sources"))[-1]
                if _object_list(payload_map.get("sources"))
                else None
            ),
        },
    )
    entry["source_record_ids"] = sorted(
        {
            parsed
            for value in [
                *_object_list(entry.get("source_record_ids")),
                record.id,
            ]
            if (parsed := _safe_int(value)) is not None
        }
    )


def _collect_fallback_selector_candidates(
    saved_selectors: list[dict[str, object]],
    *,
    run: CrawlRun,
    saved_selector_index: dict[tuple[str, str, str], dict[str, object]],
    selector_candidates: dict[str, dict[str, object]],
) -> None:
    fallback_rows = [*saved_selectors, *run.settings_view.extraction_contract()]
    for row in fallback_rows:
        field_name = str(row.get("field_name") or "").strip().lower()
        selector_value = str(row.get("css_selector") or "").strip()
        if not field_name or not selector_value:
            continue
        candidate_key = f"{field_name}|css_selector|{selector_value}"
        saved_selector = saved_selector_index.get(
            selector_signature(
                field_name=field_name,
                selector_kind="css_selector",
                selector_value=selector_value,
            )
        )
        selector_candidates[candidate_key] = {
            "candidate_key": candidate_key,
            "field_name": field_name,
            "selector_kind": "css_selector",
            "selector_value": selector_value,
            "selector_source": str(row.get("source") or "run_contract"),
            "sample_value": row.get("sample_value"),
            "source_record_ids": [],
            "source_run_id": row.get("source_run_id") or run.id,
            "saved_selector_id": saved_selector.get("id")
            if isinstance(saved_selector, dict)
            else None,
            "already_saved": isinstance(saved_selector, dict),
            "final_field_source": None,
        }


def _serialize_feedback_row(row: DomainFieldFeedback) -> dict[str, object]:
    return {
        "action": row.action,
        "source_kind": row.source_kind,
        "source_value": row.source_value,
        "source_run_id": row.source_run_id,
        "created_at": row.created_at,
    }


def _merge_affordance_candidates(
    affordance_candidates: dict[str, object],
    *,
    acquisition: dict[str, object],
    browser_diagnostics: dict[str, object],
) -> None:
    accordion_labels = _object_list(affordance_candidates.get("accordions"))
    tab_labels = _object_list(affordance_candidates.get("tabs"))
    if not affordance_candidates.get("iframe_promotion"):
        final_url = str(acquisition.get("final_url") or "").strip()
        if (
            final_url
            and final_url != str(acquisition.get("requested_url") or "").strip()
        ):
            affordance_candidates["iframe_promotion"] = final_url
    detail_expansion = mapping_or_empty(browser_diagnostics.get("detail_expansion"))
    for label in _string_values(detail_expansion.get("expanded_elements")):
        if label not in accordion_labels:
            accordion_labels.append(label)
    for label in _string_values(
        mapping_or_empty(detail_expansion.get("aom")).get("expanded_elements")
    ):
        if label not in tab_labels:
            tab_labels.append(label)
    affordance_candidates["accordions"] = accordion_labels
    affordance_candidates["tabs"] = tab_labels


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
