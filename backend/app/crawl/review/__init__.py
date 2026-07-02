# Review and promotion service.
from __future__ import annotations

from datetime import UTC, datetime

from app.models.domain_memory import (
    DomainCookieMemory,
    DomainRunProfile,
)
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.extraction_memory import ExtractionOperatorLabel
from app.core.config.extraction_memory import (
    EXTRACTION_LABEL_KIND_FIELD_FEEDBACK,
    EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
)

from app.core.config.extraction_rules import EXTRACTION_RULES, REVIEW_CONTAINER_KEYS
from app.core.db_utils import mapping_or_empty
from app.crawl.profile import (
    load_domain_run_profile,
    save_domain_run_profile,
)
from app.core.domain_utils import normalize_domain
from app.core.records.field_policy import normalize_field_key, normalize_review_target
from app.core.shared.field_coerce import (
    object_list as _object_list,
    safe_int as _safe_int,
)
from app.core.records.normalizers import normalize_value
from app.persistence.publish import (
    load_domain_field_mapping,
)
from app.persistence.record_artifacts import RecordArtifacts, load_record_artifacts
from app.core.records.schema_service import load_resolved_schema
from app.crawl.review.domain_recipe_support import (
    collect_selector_candidates,
    derive_acquisition_info,
    saved_selector_signature,
    selector_signature,
)
from app.core.records.selectors_runtime import (
    create_selector_record,
    list_selector_records,
    update_selector_record,
)
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

DomainFieldFeedback = ExtractionOperatorLabel


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    artifacts_by_id = await _load_record_artifact_views(session, records)
    domain = normalize_domain(run.url)
    canonical_fields = (await load_resolved_schema(session, run.surface, domain)).fields
    domain_mapping = await load_domain_field_mapping(
        session,
        domain=domain,
        surface=run.surface,
    )
    normalized_fields = sorted(
        {
            key
            for record in records
            for key, val in mapping_or_empty(record.data).items()
            if val not in (None, "", [], {}) and not str(key).startswith("_")
        }
    )
    discovered_field_names: set[str] = set()
    for record in records:
        for row in _review_bucket_rows(artifacts_by_id[record.id]):
            key = str(row.get("key") or "").strip()
            if key:
                discovered_field_names.add(key)
    if not discovered_field_names:
        for record in records:
            for src in (
                mapping_or_empty(artifacts_by_id[record.id].discovered_data),
                mapping_or_empty(artifacts_by_id[record.id].raw_data),
                mapping_or_empty(artifacts_by_id[record.id].data),
            ):
                for key, val in src.items():
                    if (
                        val not in (None, "", [], {})
                        and not str(key).startswith("_")
                        and key not in REVIEW_CONTAINER_KEYS
                    ):
                        discovered_field_names.add(str(key))
    discovered_fields = sorted(discovered_field_names)
    suggested_mapping = {
        field: domain_mapping.get(field, field) for field in discovered_fields
    }
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "canonical_fields": canonical_fields,
        "domain_mapping": domain_mapping,
        "suggested_mapping": suggested_mapping,
    }


async def load_review_html(session: AsyncSession, run_id: int) -> str:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return ""
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    for record in records:
        artifacts = await load_record_artifacts(session, record)
        if artifacts.html:
            return artifacts.html
    return ""


async def save_review(
    session: AsyncSession, run: CrawlRun, selections: list[dict]
) -> dict:
    selected_rows = [
        row
        for row in selections
        if bool(row.get("selected", True))
        and str(row.get("source_field") or "").strip()
        and str(row.get("output_field") or "").strip()
    ]
    domain = normalize_domain(run.url)
    mapping: dict[str, str] = {}
    for row in selected_rows:
        source_field = normalize_field_key(row.get("source_field"))
        target_field = normalize_review_target(run.surface, row.get("output_field"))
        if source_field and target_field:
            mapping[source_field] = target_field
    resolved_schema = await load_resolved_schema(session, run.surface, domain)
    next_fields = [
        *resolved_schema.fields,
        *list(mapping.values()),
    ]
    normalized_baseline_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.baseline_fields
            if (normalized_field := normalize_review_target(run.surface, field))
        )
    )
    normalized_new_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.new_fields
            if (normalized_field := normalize_review_target(run.surface, field))
        )
    )
    normalized_baseline_field_set = set(normalized_baseline_fields)
    updated_schema = resolved_schema.__class__(
        surface=resolved_schema.surface,
        domain=resolved_schema.domain,
        baseline_fields=normalized_baseline_fields,
        fields=list(dict.fromkeys(field for field in next_fields if field)),
        new_fields=list(
            dict.fromkeys(
                [
                    *normalized_new_fields,
                    *[
                        normalized_value
                        for value in mapping.values()
                        if (
                            normalized_value := normalize_review_target(
                                run.surface, value
                            )
                        )
                        and normalized_value not in normalized_baseline_field_set
                    ],
                ]
            )
        ),
        deprecated_fields=list(resolved_schema.deprecated_fields),
        source="review",
        saved_at=None,
        stale=False,
    )
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        raise RuntimeError(f"CrawlRun not found for review save: run_id={run.id}")
    saved_at = datetime.now(UTC).isoformat()
    promotion = ExtractionOperatorLabel(
        label_kind=EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
        source_run_id=db_run.id,
        domain=domain,
        surface=db_run.surface,
        approved_schema={
            "fields": updated_schema.fields,
            "baseline_fields": updated_schema.baseline_fields,
            "new_fields": updated_schema.new_fields,
            "deprecated_fields": updated_schema.deprecated_fields,
            "source": updated_schema.source,
            "saved_at": saved_at,
        },
        field_mapping=mapping,
    )
    session.add(promotion)
    await _promote_review_bucket_fields(session, db_run, mapping)
    await session.commit()
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "selected_fields": list(dict.fromkeys(mapping.values())),
        "canonical_fields": updated_schema.fields,
        "field_mapping": mapping,
    }


def _review_bucket_rows(artifacts: RecordArtifacts) -> list[dict]:
    discovered_data = mapping_or_empty(artifacts.discovered_data)
    rows = discovered_data.get("review_bucket")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def _load_record_artifact_views(
    session: AsyncSession,
    records: list[CrawlRecord],
) -> dict[int, RecordArtifacts]:
    return {
        record.id: await load_record_artifacts(session, record) for record in records
    }


async def _promote_review_bucket_fields(
    session: AsyncSession, run: CrawlRun, mapping: dict[str, str]
) -> None:
    if not mapping:
        return
    normalized_mapping = {
        normalized_source_field: normalized_target_field
        for source_field, target_field in mapping.items()
        if (normalized_source_field := normalize_field_key(source_field))
        and (normalized_target_field := normalize_field_key(target_field))
    }
    if not normalized_mapping:
        return
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )
    records = list(records_result.scalars().all())
    artifacts_by_id = await _load_record_artifact_views(session, records)
    for record in records:
        review_bucket = _review_bucket_rows(artifacts_by_id[record.id])
        if not review_bucket:
            continue

        selected_values: dict[str, dict] = {}
        remaining_rows: list[dict] = []
        for row in review_bucket:
            source_field = normalize_field_key(row.get("key"))
            output_field = normalized_mapping.get(source_field)
            if not source_field or not output_field:
                remaining_rows.append(row)
                continue
            current_value = mapping_or_empty(record.data).get(output_field)
            if current_value not in (None, "", [], {}):
                remaining_rows.append(row)
                continue
            existing = selected_values.get(output_field)
            if existing is None:
                selected_values[output_field] = row

        if not selected_values and len(remaining_rows) == len(review_bucket):
            continue

        data = dict(mapping_or_empty(record.data))
        for output_field, row in selected_values.items():
            normalized_value = normalize_value(output_field, row.get("value"))
            data[output_field] = normalized_value
        record.data = data


async def build_domain_recipe_payload(
    session: AsyncSession,
    *,
    run: CrawlRun,
) -> dict[str, object]:
    records, artifacts_by_id, domain = await _load_recipe_context(session, run)
    saved_selectors = await list_selector_records(
        session, domain=domain, surface=run.surface
    )
    found_fields, requested_fields = _resolve_recipe_fields(
        run, records, artifacts_by_id
    )
    feedback_index = await _latest_field_feedback_index(
        session, domain=domain, surface=run.surface
    )
    selector_candidates, field_learning = collect_selector_candidates(
        records,
        saved_selectors=saved_selectors,
        run=run,
        feedback_index=feedback_index,
        artifacts_by_id=artifacts_by_id,
    )
    acquisition_info = derive_acquisition_info(
        records, run=run, artifacts_by_id=artifacts_by_id
    )
    saved_profile_record = await load_domain_run_profile(
        session, domain=domain, surface=run.surface
    )
    cookie_memory_exists = await _domain_cookie_memory_exists(session, domain=domain)
    return _assemble_recipe_payload(
        run=run,
        domain=domain,
        requested_fields=requested_fields,
        found_fields=found_fields,
        acquisition_info=acquisition_info,
        selector_candidates=selector_candidates,
        field_learning=field_learning,
        saved_selectors=saved_selectors,
        saved_profile_record=saved_profile_record,
        cookie_memory_exists=cookie_memory_exists,
    )


async def _load_recipe_context(
    session: AsyncSession,
    run: CrawlRun,
) -> tuple[list[CrawlRecord], dict[int, RecordArtifacts], str]:
    records_result = await session.execute(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run.id)
        .order_by(CrawlRecord.id.asc())
    )
    records = list(records_result.scalars().all())
    artifacts_by_id = await _load_record_artifact_views(session, records)
    return records, artifacts_by_id, normalize_domain(run.url)


def _resolve_recipe_fields(
    run: CrawlRun,
    records: list[CrawlRecord],
    artifacts_by_id: dict[int, RecordArtifacts],
) -> tuple[list[str], list[str]]:
    found_fields = sorted(
        {
            str(field_name)
            for record in records
            for field_name, value in mapping_or_empty(record.data).items()
            if value not in (None, "", [], {})
        }
        | {
            str(field_name)
            for record in records
            for field_name, payload in mapping_or_empty(
                artifacts_by_id[record.id].source_trace.get("field_discovery")
            ).items()
            if isinstance(payload, dict) and payload.get("status") == "found"
        }
    )
    requested_fields = [
        str(value) for value in run.requested_fields or [] if str(value or "").strip()
    ]
    if not found_fields and requested_fields:
        dom_patterns = mapping_or_empty(EXTRACTION_RULES.get("dom_patterns"))
        found_fields = sorted(
            f for f in requested_fields if str(dom_patterns.get(f) or "").strip()
        )
    return found_fields, requested_fields


def _assemble_recipe_payload(
    *,
    run: CrawlRun,
    domain: str,
    requested_fields: list[str],
    found_fields: list[str],
    acquisition_info: dict[str, object],
    selector_candidates: dict[str, dict[str, object]],
    field_learning: dict[tuple[str, str, str], dict[str, object]],
    saved_selectors: list[dict[str, object]],
    saved_profile_record: DomainRunProfile | None,
    cookie_memory_exists: bool,
) -> dict[str, object]:
    actual_fetch_method = acquisition_info["actual_fetch_method"]
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "requested_field_coverage": {
            "requested": requested_fields,
            "found": [f for f in requested_fields if f in found_fields],
            "missing": [f for f in requested_fields if f not in found_fields],
        },
        "acquisition_evidence": {
            "actual_fetch_method": actual_fetch_method,
            "browser_used": actual_fetch_method == "browser",
            "browser_reason": acquisition_info["browser_reason"],
            "acquisition_summary": acquisition_info["acquisition_summary"],
            "cookie_memory_available": cookie_memory_exists,
        },
        "field_learning": sorted(
            field_learning.values(),
            key=lambda row: (
                str(row.get("field_name") or ""),
                str(row.get("selector_kind") or ""),
                str(row.get("selector_value") or ""),
            ),
        ),
        "selector_candidates": sorted(
            selector_candidates.values(),
            key=lambda row: (
                str(row.get("field_name") or ""),
                str(row.get("selector_kind") or ""),
                str(row.get("selector_value") or ""),
            ),
        ),
        "affordance_candidates": acquisition_info["affordance_candidates"],
        "saved_selectors": saved_selectors,
        "saved_run_profile": (
            dict(saved_profile_record.profile or {})
            if saved_profile_record is not None
            else None
        ),
    }


async def promote_domain_recipe_selectors(
    session: AsyncSession,
    *,
    run: CrawlRun,
    selectors: list[dict[str, object]],
    commit: bool = True,
) -> list[dict[str, object]]:
    domain = normalize_domain(run.url)
    existing = await list_selector_records(
        session,
        domain=domain,
        surface=run.surface,
    )
    by_signature = {saved_selector_signature(row): row for row in existing}
    saved_rows: list[dict[str, object]] = []
    for row in selectors:
        selector_kind = str(row.get("selector_kind") or "").strip()
        selector_value = str(row.get("selector_value") or "").strip()
        field_name = normalize_field_key(str(row.get("field_name") or ""))
        if not field_name or selector_kind != "css_selector" or not selector_value:
            continue
        payload = {
            "field_name": field_name,
            "css_selector": selector_value,
            "sample_value": row.get("sample_value"),
            "source": "domain_recipe",
            "source_run_id": run.id,
            "status": "validated",
            "is_active": True,
        }
        signature = selector_signature(
            field_name=field_name,
            selector_kind=selector_kind,
            selector_value=selector_value,
        )
        existing_row = by_signature.get(signature)
        if (
            isinstance(existing_row, dict)
            and "id" in existing_row
            and existing_row["id"] is not None
        ):
            selector_id = _safe_int(existing_row.get("id"))
            if selector_id is None:
                continue
            updated_row = await update_selector_record(
                session,
                selector_id=selector_id,
                payload=payload,
                commit=commit,
            )
            if updated_row is not None:
                saved_rows.append(updated_row)
            continue
        created_row = await create_selector_record(
            session,
            domain=domain,
            surface=run.surface,
            payload=payload,
            commit=commit,
        )
        if created_row is not None:
            saved_rows.append(created_row)
    return [row for row in saved_rows if isinstance(row, dict)]


async def save_domain_recipe_run_profile(
    session: AsyncSession,
    *,
    run: CrawlRun,
    profile: dict[str, object],
) -> dict[str, object]:
    return await save_domain_run_profile(
        session,
        domain=normalize_domain(run.url),
        surface=run.surface,
        profile=profile,
        source_run_id=run.id,
        commit=True,
    )


async def apply_domain_recipe_field_action(
    session: AsyncSession,
    *,
    run: CrawlRun,
    action: dict[str, object],
) -> dict[str, object]:
    domain = normalize_domain(run.url)
    field_name = normalize_field_key(str(action.get("field_name") or ""))
    action_name = str(action.get("action") or "").strip().lower()
    selector_kind = str(action.get("selector_kind") or "").strip().lower()
    selector_value = str(action.get("selector_value") or "").strip()
    if not field_name or action_name not in {"keep", "reject"}:
        raise ValueError("Invalid domain recipe field action.")
    if selector_kind and selector_kind != "css_selector":
        raise ValueError("Only css_selector domain recipe actions are supported.")

    source_kind = "selector" if selector_kind and selector_value else "field_source"
    source_value = selector_value or None
    try:
        if action_name == "keep" and selector_kind and selector_value:
            await promote_domain_recipe_selectors(
                session,
                run=run,
                selectors=[
                    {
                        "field_name": field_name,
                        "selector_kind": selector_kind,
                        "selector_value": selector_value,
                    }
                ],
                commit=False,
            )
        if action_name == "reject" and selector_kind and selector_value:
            existing = await list_selector_records(
                session,
                domain=domain,
                surface=run.surface,
            )
            for row in existing:
                matched_value = row.get("css_selector")
                if (
                    normalize_field_key(str(row.get("field_name") or "")) == field_name
                    and str(matched_value or "").strip() == selector_value
                    and row.get("id") is not None
                ):
                    selector_id = _safe_int(row.get("id"))
                    if selector_id is None:
                        continue
                    await update_selector_record(
                        session,
                        selector_id=selector_id,
                        payload={"is_active": False},
                        commit=False,
                    )
                    break

        feedback = DomainFieldFeedback(
            label_kind=EXTRACTION_LABEL_KIND_FIELD_FEEDBACK,
            domain=domain,
            surface=run.surface,
            field_name=field_name,
            action=action_name,
            source_kind=source_kind,
            source_value=source_value,
            source_run_id=run.id,
            payload={
                "selector_kind": selector_kind or None,
                "selector_value": selector_value or None,
                "source_record_ids": [
                    parsed
                    for parsed in (
                        _safe_int(value)
                        for value in _object_list(action.get("source_record_ids"))
                    )
                    if parsed is not None
                ],
            },
        )
        session.add(feedback)
        await session.commit()
        await session.refresh(feedback)
        return _serialize_feedback_row(feedback)
    except Exception:
        await session.rollback()
        raise


async def list_domain_field_feedback(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
    limit: int = 50,
) -> list[dict[str, object]]:
    statement = (
        select(DomainFieldFeedback)
        .where(DomainFieldFeedback.label_kind == EXTRACTION_LABEL_KIND_FIELD_FEEDBACK)
        .order_by(
            desc(DomainFieldFeedback.created_at),
            desc(DomainFieldFeedback.id),
        )
    )
    if domain:
        statement = statement.where(DomainFieldFeedback.domain == domain)
    if surface:
        statement = statement.where(DomainFieldFeedback.surface == surface)
    rows = list((await session.execute(statement.limit(max(1, limit)))).scalars().all())
    return [_serialize_feedback_record(row) for row in rows]


async def _domain_cookie_memory_exists(
    session: AsyncSession,
    *,
    domain: str,
) -> bool:
    result = await session.execute(
        select(DomainCookieMemory.id)
        .where(DomainCookieMemory.domain == domain)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _latest_field_feedback_index(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[tuple[str, str, str], DomainFieldFeedback]:
    rows = list(
        (
            await session.execute(
                select(DomainFieldFeedback)
                .where(
                    DomainFieldFeedback.label_kind
                    == EXTRACTION_LABEL_KIND_FIELD_FEEDBACK,
                    DomainFieldFeedback.domain == domain,
                    DomainFieldFeedback.surface == surface,
                )
                .order_by(
                    desc(DomainFieldFeedback.created_at), desc(DomainFieldFeedback.id)
                )
            )
        )
        .scalars()
        .all()
    )
    index: dict[tuple[str, str, str], DomainFieldFeedback] = {}
    for row in rows:
        key = (
            str(row.field_name or "").strip().lower(),
            str((row.payload or {}).get("selector_kind") or "").strip(),
            str(row.source_value or "").strip(),
        )
        index.setdefault(key, row)
    return index


def _serialize_feedback_row(row: DomainFieldFeedback) -> dict[str, object]:
    return {
        "action": row.action,
        "source_kind": row.source_kind,
        "source_value": row.source_value,
        "source_run_id": row.source_run_id,
        "created_at": row.created_at,
    }


def _serialize_feedback_record(row: DomainFieldFeedback) -> dict[str, object]:
    payload = row.payload or {}
    return {
        "id": row.id,
        "domain": row.domain,
        "surface": row.surface,
        "field_name": row.field_name,
        "action": row.action,
        "source_kind": row.source_kind,
        "source_value": row.source_value,
        "source_run_id": row.source_run_id,
        "selector_kind": payload.get("selector_kind"),
        "selector_value": payload.get("selector_value"),
        "source_record_ids": [
            parsed
            for parsed in (
                _safe_int(value) for value in payload.get("source_record_ids") or []
            )
            if parsed is not None
        ],
        "created_at": row.created_at,
    }
