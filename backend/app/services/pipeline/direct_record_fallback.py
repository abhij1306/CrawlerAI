from __future__ import annotations

import json
from typing import Awaitable, Callable

from app.models.crawl_run import CrawlRun
from app.services.confidence import score_record_confidence
from app.services.config.llm_runtime import llm_runtime_settings
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.field_policy import (
    field_allowed_for_surface,
    repair_target_fields_for_surface,
)
from app.services.db_utils import mapping_or_empty
from app.services.shared.field_coerce import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    URL_FIELDS,
    coerce_field_value,
    finalize_record,
    strip_html_tags,
)
from app.services.llm.runtime import extract_missing_fields
from app.services.shared.coerce_primitives import string_list
from sqlalchemy.ext.asyncio import AsyncSession


ResolveRunConfigFn = Callable[..., Awaitable[dict[str, object] | None]]
ExtractRecordsFn = Callable[..., Awaitable[tuple[list[dict[str, object]] | None, str | None]]]


def _sanitize_llm_existing_values(record: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    max_chars = max(1, int(llm_runtime_settings.existing_values_max_chars or 1))
    for key, value in record.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, str):
            truncated = value
            if "<" in truncated and ">" in truncated:
                truncated = strip_html_tags(truncated)
            truncated = truncated[:max_chars]
            sanitized[key] = truncated
        elif isinstance(value, (list, dict)):
            serialized = json.dumps(value, default=str)
            if len(serialized) > max_chars:
                serialized = serialized[:max_chars]
            sanitized[key] = serialized
        else:
            sanitized[key] = value
    return sanitized


_STRING_FIELDS = URL_FIELDS | IMAGE_FIELDS | LONG_TEXT_FIELDS
_LIST_FIELDS = STRUCTURED_MULTI_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
_DICT_FIELDS = STRUCTURED_OBJECT_FIELDS


def _validate_llm_field_type(field_name: str, value: object) -> bool:
    if value in (None, "", [], {}):
        return True
    normalized = str(field_name or "").strip().lower()
    if normalized in _STRING_FIELDS:
        return isinstance(value, str)
    if normalized in _LIST_FIELDS:
        return isinstance(value, list)
    if normalized in _DICT_FIELDS:
        return isinstance(value, dict)
    return True


async def apply_direct_record_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    records: list[dict[str, object]],
    resolve_run_config_fn: ResolveRunConfigFn,
    extract_records_fn: ExtractRecordsFn,
) -> list[dict[str, object]]:
    if not records:
        return records
    if "detail" in str(run.surface or ""):
        return records
    domain = normalize_domain(page_url)
    requested_fields = repair_target_fields_for_surface(
        run.surface,
        run.requested_fields or [],
    )
    missing_by_record = [
        [
            field_name
            for field_name in requested_fields
            if field_allowed_for_surface(run.surface, field_name)
            and record.get(field_name) in (None, "", [], {})
        ]
        for record in records
    ]
    if not any(missing_by_record):
        return records
    config = await resolve_run_config_fn(
        session,
        run_id=run.id,
        task_type="direct_record_extraction",
    )
    if not config:
        return records
    candidates, _error_message = await extract_records_fn(
        session,
        run_id=run.id,
        domain=domain,
        url=page_url,
        surface=run.surface,
        html_text=html,
        requested_fields=requested_fields,
        existing_records=records,
    )
    if not candidates:
        return records

    updated_records: list[dict[str, object]] = []
    for index, record in enumerate(records):
        next_record = dict(record)
        candidate = candidates[index] if index < len(candidates) else None
        if isinstance(candidate, dict):
            for field_name in missing_by_record[index]:
                value = candidate.get(field_name)
                if value in (None, "", [], {}) or not _validate_llm_field_type(
                    field_name, value
                ):
                    continue
                next_record[field_name] = coerce_field_value(field_name, value, page_url)
        updated_records.append(finalize_record(next_record, surface=run.surface))
    return updated_records


async def apply_llm_fallback(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    updated_records: list[dict[str, object]] = []
    domain = normalize_domain(page_url)
    requested_fields = repair_target_fields_for_surface(
        run.surface,
        run.requested_fields or [],
    )
    for record in records:
        next_record = dict(record)
        missing_fields = [
            field_name
            for field_name in requested_fields
            if field_allowed_for_surface(run.surface, field_name)
            and next_record.get(field_name) in (None, "", [], {})
        ]
        should_run = bool(missing_fields)
        if not should_run:
            updated_records.append(next_record)
            continue
        sanitized_existing = _sanitize_llm_existing_values(next_record)
        payload, error_message = await extract_missing_fields(
            session,
            run_id=run.id,
            domain=domain,
            url=page_url,
            html_text=html,
            missing_fields=missing_fields or requested_fields,
            existing_values=sanitized_existing,
        )
        field_sources = mapping_or_empty(next_record.get("_field_sources"))
        applied_llm_fields: list[str] = []
        llm_rejected_fields: list[str] = []
        if isinstance(payload, dict):
            for field_name, value in payload.items():
                normalized_field = str(field_name or "").strip().lower()
                if (
                    not normalized_field
                    or not field_allowed_for_surface(run.surface, normalized_field)
                    or next_record.get(normalized_field) not in (None, "", [], {})
                ):
                    continue
                coerced = coerce_field_value(
                    normalized_field,
                    value,
                    page_url,
                )
                if not _validate_llm_field_type(normalized_field, coerced):
                    llm_rejected_fields.append(normalized_field)
                    continue
                if coerced in (None, "", [], {}):
                    continue
                next_record[normalized_field] = coerced
                applied_llm_fields.append(normalized_field)
                current_sources = string_list(field_sources.get(normalized_field))
                if "llm_missing_field_extraction" not in current_sources:
                    current_sources.append("llm_missing_field_extraction")
                field_sources[normalized_field] = current_sources
        if applied_llm_fields:
            canonical_record = {
                key: value
                for key, value in next_record.items()
                if not str(key).startswith("_")
            }
            next_record.update(finalize_record(canonical_record, surface=run.surface))
        next_record["_field_sources"] = field_sources
        next_record["_confidence"] = score_record_confidence(
            next_record,
            surface=run.surface,
            requested_fields=requested_fields,
        )
        if applied_llm_fields and not str(next_record.get("_source") or "").strip():
            next_record["_source"] = "llm_missing_field_extraction"
        next_record["_self_heal"] = {
            "enabled": True,
            "triggered": True,
            "threshold": crawler_runtime_settings.llm_confidence_threshold,
            "mode": "missing_field_extraction",
            "error": error_message or None,
            "rejected_fields": llm_rejected_fields or None,
        }
        updated_records.append(next_record)
    return updated_records
