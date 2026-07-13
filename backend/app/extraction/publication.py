"""Resolver-owned publication policy for extraction surfaces."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from app.core.config import field_mappings
from app.core.config.variant_policy import NON_PUBLIC_VARIANT_IDENTITY_FIELDS
from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeExecutionResult,
)
from app.extraction.contracts import (
    CanonicalizationTrace,
    CommerceDetailProjection,
    CommerceListingProjection,
    CommerceDetailRecord,
    CommerceListingRecord,
    CommerceVariantRecord,
    ExtractionRequest,
    Finding,
    Evidence,
    JobDetailProjection,
    JobDetailRecord,
    JobListingRecord,
    JobListingProjection,
    PublicationEntry,
    PublicRecord,
    ResolutionResult,
    SelectedFact,
)
from app.core.shared.ids import stable_id
from app.core.shared.url_utils import public_asset_delivery_url
from app.extraction.surfaces import Surface
from app.extraction.validation import validate_selected_contract_fields

PUBLIC_FACT_TO_FIELD = {
    field_mappings.PRODUCT_URL_FACT_TYPE: "url",
    field_mappings.PRODUCT_TITLE_FACT_TYPE: "title",
    field_mappings.PRODUCT_BRAND_FACT_TYPE: "brand",
    field_mappings.PRODUCT_DESCRIPTION_FACT_TYPE: "description",
    "product.category": "category",
    field_mappings.PRODUCT_SKU_FACT_TYPE: "sku",
    field_mappings.PRODUCT_MPN_FACT_TYPE: "mpn",
    field_mappings.PRODUCT_GTIN_FACT_TYPE: "gtin",
    field_mappings.OFFER_PRICE_FACT_TYPE: "price",
    "offer.price_min": "price_min",
    "offer.price_max": "price_max",
    field_mappings.OFFER_CURRENCY_FACT_TYPE: "currency",
    field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE: "original_price",
    field_mappings.OFFER_AVAILABILITY_FACT_TYPE: "availability",
}

_EMPTY: tuple[object, ...] = (None, "", [], {}, ())
_PRICE_FACTS = {
    field_mappings.OFFER_PRICE_FACT_TYPE,
    field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    "offer.price_min",
    "offer.price_max",
}

_COMMERCE_LISTING_FIELDS = {
    "product.title": "title",
    "product.url": "url",
    "offer.price": "price",
    "asset.image_url": "image_url",
}
_JOB_DETAIL_FIELDS = {
    "job.title": "title",
    "job.id": "job_id",
    "job.company": "company",
    "job.location": "location",
    "job.type": "job_type",
    "job.posted_date": "posted_date",
    "job.url": "url",
    "job.apply_url": "apply_url",
    "job.description": "description",
}
_JOB_LISTING_FIELDS = {
    "job.title": "title",
    "job.url": "url",
    "job.company": "company",
    "job.location": "location",
}
_PATH = re.compile(r"^(record|variant|asset)(?:\[([^]]+)])?\.(.+)$")


def _selected_facts(
    decisions: tuple,
    evidence: tuple[Evidence, ...],
) -> tuple[SelectedFact, ...]:
    evidence_by_id = {row.evidence_id: row for row in evidence}
    return tuple(
        SelectedFact(
            selected_fact_id=stable_id("selected", decision.decision_id),
            decision_id=decision.decision_id,
            entity_id=decision.entity_id,
            fact_type=decision.fact_type,
            value=accepted.value,
            evidence_ids=decision.accepted_evidence_ids,
            rule_id=decision.rule_id,
        )
        for decision in decisions
        if decision.status == "resolved"
        and len(decision.accepted_evidence_ids) == 1
        and (accepted := evidence_by_id.get(decision.accepted_evidence_ids[0]))
        is not None
    )


def commerce_detail_projection(
    resolution: ResolutionResult,
    evidence: Sequence[Evidence],
) -> tuple[CommerceDetailProjection, tuple[SelectedFact, ...]]:
    """Authorize scalar ecommerce-detail publication from resolved truth."""

    evidence_by_id = {row.evidence_id: row for row in evidence}
    derived_by_key = {
        (row.entity_id, row.fact_type): row for row in resolution.derived_facts
    }
    target_ids = {
        value
        for value in (
            resolution.primary_product_entity_id,
            resolution.primary_offer_entity_id,
        )
        if value
    }
    selected_facts = _selected_facts(resolution.decisions, tuple(evidence))
    selected_by_decision = {row.decision_id: row for row in selected_facts}
    selected_by_entity_fact = {
        (row.entity_id, row.fact_type): row for row in selected_facts
    }
    variant_skus = {
        str(row.values.get("sku"))
        for row in resolution.variant_decisions
        if row.status == "eligible" and row.values.get("sku") not in _EMPTY
    }
    resolved_keys = {
        (row.entity_id, row.fact_type)
        for row in resolution.decisions
        if row.status == "resolved"
    } | set(derived_by_key)
    has_primary_price = any(
        (resolution.primary_offer_entity_id, fact_type) in resolved_keys
        for fact_type in _PRICE_FACTS
    )

    has_child_price = any(
        fact_type in _PRICE_FACTS and entity_id != resolution.primary_offer_entity_id
        for entity_id, fact_type in resolved_keys
    ) or any(
        row.status == "eligible" and row.values.get("price") not in _EMPTY
        for row in resolution.variant_decisions
    )
    has_primary_currency = (
        resolution.primary_offer_entity_id,
        field_mappings.OFFER_CURRENCY_FACT_TYPE,
    ) in resolved_keys

    entries: list[PublicationEntry] = []
    for decision in resolution.decisions:
        field = PUBLIC_FACT_TO_FIELD.get(decision.fact_type)
        if (
            field is None
            or decision.entity_id not in target_ids
            or decision.status != "resolved"
            or not decision.accepted_evidence_ids
        ):
            continue
        accepted = evidence_by_id.get(decision.accepted_evidence_ids[0])
        if accepted is None:
            continue
        disposition, reason = _publication_disposition(
            fact_type=decision.fact_type,
            value=accepted.value,
            variant_skus=variant_skus,
            has_primary_price=has_primary_price,
            has_child_price=has_child_price,
            has_primary_currency=has_primary_currency,
        )
        derived = derived_by_key.get((decision.entity_id, decision.fact_type))
        if derived is not None:
            selected = selected_by_decision.get(decision.decision_id)
            if selected is not None and selected.value == derived.value:
                derived = None
        if derived is not None:
            entries.append(
                PublicationEntry(
                    path=f"record.{field}",
                    entity_id=decision.entity_id,
                    value=derived.value,
                    disposition=disposition,
                    reason_code=reason,
                    derived_fact_id=derived.derived_fact_id,
                    rule_id=derived.rule_id,
                    evidence_ids=derived.input_evidence_ids,
                    collector_ids=_collector_ids(
                        derived.input_evidence_ids, evidence_by_id
                    ),
                )
            )
            continue
        selected = selected_by_decision.get(decision.decision_id)
        if selected is not None:
            entries.append(
                PublicationEntry(
                    path=f"record.{field}",
                    entity_id=decision.entity_id,
                    value=selected.value,
                    disposition=disposition,
                    reason_code=reason,
                    selected_fact_id=selected.selected_fact_id,
                    rule_id=selected.rule_id,
                    evidence_ids=selected.evidence_ids,
                    collector_ids=_collector_ids(selected.evidence_ids, evidence_by_id),
                )
            )

    authorized_paths = {row.path for row in entries}
    for derived in resolution.derived_facts:
        field = PUBLIC_FACT_TO_FIELD.get(derived.fact_type)
        path = f"record.{field}" if field else ""
        if not field or path in authorized_paths or derived.entity_id not in target_ids:
            continue
        disposition, reason = _publication_disposition(
            fact_type=derived.fact_type,
            value=derived.value,
            variant_skus=variant_skus,
            has_primary_price=has_primary_price,
            has_child_price=has_child_price,
            has_primary_currency=has_primary_currency,
        )
        entries.append(
            PublicationEntry(
                path=path,
                entity_id=derived.entity_id,
                value=derived.value,
                disposition=disposition,
                reason_code=reason,
                derived_fact_id=derived.derived_fact_id,
                rule_id=derived.rule_id,
                evidence_ids=derived.input_evidence_ids,
                collector_ids=_collector_ids(
                    derived.input_evidence_ids, evidence_by_id
                ),
            )
        )
        authorized_paths.add(path)

    for variant in resolution.variant_decisions:
        if variant.status != "eligible":
            continue
        for field, value in variant.values.items():
            if field in NON_PUBLIC_VARIANT_IDENTITY_FIELDS:
                continue
            source = _publication_source(variant.lineage.get(field))
            if source is None:
                continue
            entries.append(
                PublicationEntry(
                    path=f"variant[{variant.variant_entity_id}].{field}",
                    entity_id=variant.variant_entity_id,
                    parent_entity_id=resolution.primary_product_entity_id,
                    value=value,
                    collector_ids=_collector_ids(
                        tuple(source.get("evidence_ids", ())), evidence_by_id
                    ),
                    **source,
                )
            )

    asset_entries, emitted_asset_ids, primary_asset_entity_id = _asset_entries(
        resolution, selected_by_entity_fact, evidence_by_id
    )
    entries.extend(asset_entries)
    return (
        CommerceDetailProjection(
            record_entity_id=resolution.primary_product_entity_id or "unresolved",
            entries=tuple(entries),
            variant_entity_ids=tuple(
                row.variant_entity_id
                for row in resolution.variant_decisions
                if row.status == "eligible"
            ),
            asset_entity_ids=tuple(emitted_asset_ids),
            primary_asset_entity_id=primary_asset_entity_id,
        ),
        selected_facts,
    )


def _asset_entries(
    resolution: ResolutionResult,
    selected_by_entity_fact: dict[tuple[str, str], SelectedFact],
    evidence_by_id: dict[str, Evidence],
) -> tuple[tuple[PublicationEntry, ...], tuple[str, ...], str | None]:
    derived_by_entity_fact = {
        (row.entity_id, row.fact_type): row for row in resolution.derived_facts
    }
    entries: list[PublicationEntry] = []
    emitted_asset_ids: list[str] = []
    primary_asset_entity_id: str | None = None
    for asset in resolution.asset_decisions:
        if not (asset.asset_entity_id and asset.url and asset.accepted_evidence_ids):
            continue
        selected = selected_by_entity_fact.get(
            (asset.asset_entity_id, field_mappings.ASSET_IMAGE_URL_FACT_TYPE)
        )
        delivery_url = public_asset_delivery_url(asset.url)
        if selected is None or delivery_url is None:
            continue
        entries.append(
            PublicationEntry(
                path=f"asset[{asset.asset_entity_id}].url",
                entity_id=asset.asset_entity_id,
                parent_entity_id=resolution.primary_product_entity_id,
                value=selected.value,
                selected_fact_id=selected.selected_fact_id,
                rule_id=asset.rule_id,
                evidence_ids=asset.accepted_evidence_ids,
                collector_ids=_collector_ids(
                    asset.accepted_evidence_ids, evidence_by_id
                ),
                canonicalization=CanonicalizationTrace(
                    raw_value=selected.value,
                    canonical_value=delivery_url,
                    canonicalizer_id="image_delivery_url",
                    canonicalizer_version="1",
                ),
            )
        )
        emitted_asset_ids.append(asset.asset_entity_id)
        if asset.role == "primary":
            primary_asset_entity_id = asset.asset_entity_id
        role = derived_by_entity_fact.get((asset.asset_entity_id, "asset.role"))
        if role is not None:
            entries.append(
                PublicationEntry(
                    path=f"asset[{asset.asset_entity_id}].role",
                    entity_id=asset.asset_entity_id,
                    parent_entity_id=resolution.primary_product_entity_id,
                    value=role.value,
                    derived_fact_id=role.derived_fact_id,
                    rule_id=role.rule_id,
                    evidence_ids=role.input_evidence_ids,
                    collector_ids=_collector_ids(
                        role.input_evidence_ids, evidence_by_id
                    ),
                )
            )
    return tuple(entries), tuple(emitted_asset_ids), primary_asset_entity_id


def commerce_listing_projection(
    decisions,
    evidence: Sequence[Evidence],
    *,
    max_records: int,
) -> tuple[CommerceListingProjection, tuple[SelectedFact, ...]]:
    return _many_record_projection(
        projection_type=CommerceListingProjection,
        decisions=decisions,
        evidence=evidence,
        field_map=_COMMERCE_LISTING_FIELDS,
        required_fields={"title", "url"},
        max_records=max_records,
    )


def job_listing_projection(
    decisions,
    evidence: Sequence[Evidence],
    *,
    max_records: int,
) -> tuple[JobListingProjection, tuple[SelectedFact, ...]]:
    return _many_record_projection(
        projection_type=JobListingProjection,
        decisions=decisions,
        evidence=evidence,
        field_map=_JOB_LISTING_FIELDS,
        required_fields={"title", "url"},
        max_records=max_records,
    )


def job_detail_projection(
    decisions,
    evidence: Sequence[Evidence],
    *,
    target_entity_id: str | None,
) -> tuple[JobDetailProjection, tuple[SelectedFact, ...]]:
    selected = _selected_facts(tuple(decisions), tuple(evidence))
    evidence_by_id = {item.evidence_id: item for item in evidence}
    entries = tuple(
        PublicationEntry(
            path=f"record.{_JOB_DETAIL_FIELDS[row.fact_type]}",
            entity_id=row.entity_id,
            value=row.value,
            selected_fact_id=row.selected_fact_id,
            rule_id=row.rule_id,
            evidence_ids=row.evidence_ids,
            collector_ids=_collector_ids(row.evidence_ids, evidence_by_id),
        )
        for row in selected
        if row.entity_id == target_entity_id and row.fact_type in _JOB_DETAIL_FIELDS
    )
    has_title = any(row.path == "record.title" for row in entries)
    return (
        JobDetailProjection(
            record_entity_id=target_entity_id or "unresolved",
            entries=entries if has_title else (),
        ),
        selected,
    )


def _many_record_projection(
    *,
    projection_type,
    decisions,
    evidence: Sequence[Evidence],
    field_map: dict[str, str],
    required_fields: set[str],
    max_records: int,
):
    selected = _selected_facts(tuple(decisions), tuple(evidence))
    evidence_by_id = {row.evidence_id: row for row in evidence}
    by_entity: dict[str, list[SelectedFact]] = {}
    for row in selected:
        if row.fact_type in field_map:
            by_entity.setdefault(row.entity_id, []).append(row)
    candidates: list[tuple[str, str, list[SelectedFact]]] = []
    seen_urls: set[str] = set()
    for entity_id, rows in by_entity.items():
        fields = {field_map[row.fact_type] for row in rows}
        if not required_fields <= fields:
            continue
        url = next(str(row.value) for row in rows if field_map[row.fact_type] == "url")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append((url, entity_id, rows))
    candidates.sort(key=lambda item: (item[0], item[1]))
    chosen = candidates[:max_records]
    entity_ids = tuple(entity_id for _url, entity_id, _rows in chosen)
    entries = tuple(
        PublicationEntry(
            path=f"record[{entity_id}].{field_map[row.fact_type]}",
            entity_id=entity_id,
            value=row.value,
            selected_fact_id=row.selected_fact_id,
            rule_id=row.rule_id,
            evidence_ids=row.evidence_ids,
            collector_ids=_collector_ids(row.evidence_ids, evidence_by_id),
        )
        for _url, entity_id, rows in chosen
        for row in rows
    )
    return projection_type(record_entity_ids=entity_ids, entries=entries), selected


class _PublicationSource(TypedDict, total=False):
    selected_fact_id: str
    derived_fact_id: str
    rule_id: str
    evidence_ids: tuple[str, ...]


def _publication_source(lineage: object) -> _PublicationSource | None:
    if not isinstance(lineage, dict):
        return None
    if selected_fact_id := lineage.get("selected_fact_id"):
        source = _PublicationSource(selected_fact_id=str(selected_fact_id))
    elif derived_fact_id := lineage.get("derived_fact_id"):
        source = _PublicationSource(derived_fact_id=str(derived_fact_id))
    else:
        return None
    if rule_id := lineage.get("rule_id"):
        source["rule_id"] = str(rule_id)
    evidence_ids = lineage.get("evidence_ids")
    if isinstance(evidence_ids, (list, tuple)):
        source["evidence_ids"] = tuple(str(item) for item in evidence_ids)
    return source


def _collector_ids(
    evidence_ids: tuple[str, ...], evidence_by_id: dict[str, Evidence]
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence_by_id[evidence_id].collector_id
            for evidence_id in evidence_ids
            if evidence_id in evidence_by_id
        )
    )


def _publication_disposition(
    *,
    fact_type: str,
    value: object,
    variant_skus: set[str],
    has_primary_price: bool,
    has_child_price: bool,
    has_primary_currency: bool,
) -> tuple[Literal["publish", "suppress", "review"], str | None]:
    if (
        fact_type == field_mappings.PRODUCT_SKU_FACT_TYPE
        and len(variant_skus) > 1
        and str(value) in variant_skus
    ):
        return "suppress", "parent_sku_is_variant_specific"
    if fact_type in _PRICE_FACTS and not has_primary_currency:
        return "suppress", "currency_unresolved"
    if fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE and not (
        has_primary_price or has_child_price
    ):
        return "suppress", "price_unresolved"
    return "publish", None


_MODEL_BY_SURFACE = {
    Surface.ECOMMERCE_DETAIL: CommerceDetailRecord,
    Surface.ECOMMERCE_LISTING: CommerceListingRecord,
    Surface.JOB_DETAIL: JobDetailRecord,
    Surface.JOB_LISTING: JobListingRecord,
}


def publish_recipe_execution(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
) -> tuple[tuple[PublicRecord, ...], tuple[Finding, ...]]:
    """Project authorized executor values. No discovery or semantic repair."""

    model: Any = _MODEL_BY_SURFACE[request.surface]
    field_sources = _field_sources(recipe, execution)
    records: list[PublicRecord] = []
    for index, raw in enumerate(execution.records[: request.max_records]):
        lineage = _lineage(recipe, execution, record_index=index)
        payload = _public_payload(model, raw)
        variant_lineage: list[dict[str, object]] = []
        if model is CommerceDetailRecord:
            variant_rows = sorted(
                (dict(row) for row in raw.get("variants", ()) if isinstance(row, dict)),
                key=lambda row: tuple(
                    str(row.get(field) or "")
                    for field in ("variant_id", "sku", "color", "size")
                ),
            )
            variant_records: list[CommerceVariantRecord] = []
            for row in variant_rows:
                row_lineage = row.pop("_binding_lineage", {})
                variant_records.append(CommerceVariantRecord.model_validate(row))
                variant_lineage.append(dict(row_lineage))
            variants = tuple(variant_records)
            payload["variants"] = variants
            payload["variant_count"] = len(variants)
            if isinstance(raw.get("additional_images"), (list, tuple)):
                payload["additional_images"] = tuple(raw["additional_images"])
        subject_id = stable_id(
            "recipe-record", request.capture.bundle_id, execution.recipe_id, index
        )
        if variant_lineage:
            lineage["variants"] = variant_lineage
        payload.update(
            {
                "_subject_id": subject_id,
                "_record_key": subject_id,
                "_lineage": lineage,
                "_field_sources": field_sources,
            }
        )
        records.append(model.model_validate(payload))
    result = tuple(records)
    findings = (
        validate_selected_contract_fields(
            result,
            request.requested_fields,
        )
        if request.surface is Surface.ECOMMERCE_DETAIL
        else ()
    )
    return result, findings


def _public_payload(model, raw: dict[str, object]) -> dict[str, object]:
    allowed = set(model.model_fields)
    return {key: value for key, value in raw.items() if key in allowed}


def _lineage(
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
    *,
    record_index: int = 0,
) -> dict[str, object]:
    bindings = {
        binding.binding_id: binding
        for binding in (
            recipe.record_root,
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    public_fields = {
        binding.field for binding in sum(recipe.fields.values(), ()) if binding.field
    }
    grouped: dict[str, list[dict[str, object]]] = {}
    for outcome in execution.outcomes:
        if outcome.status != "resolved" or not outcome.source_path:
            continue
        binding = bindings.get(outcome.binding_id)
        field = binding.field if binding is not None else None
        if outcome.binding_id.startswith("record.identity."):
            field = outcome.binding_id.rsplit(".", 1)[-1]
            if field in public_fields:
                continue
        if not field or ("." in field and not outcome.binding_id.startswith("field.")):
            continue
        grouped.setdefault(field, []).append(
            {
                "recipe_id": execution.recipe_id,
                "binding_id": outcome.binding_id,
                "source_path": outcome.source_path,
                "rule_id": binding.rule_id if binding else None,
                "derived_fact_id": stable_id(
                    "recipe-fact", execution.recipe_id, outcome.binding_id
                ),
            }
        )
    listing = recipe.scope.surface.endswith("_listing")
    return {
        field: rows[min(record_index, len(rows) - 1)]
        if listing or len(rows) == 1
        else rows
        for field, rows in grouped.items()
    }


def _field_sources(
    recipe: ExtractionRecipe, execution: RecipeExecutionResult
) -> dict[str, list[str]]:
    bindings = {
        binding.binding_id: binding
        for binding in (
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    sources: dict[str, set[str]] = {}
    for outcome in execution.outcomes:
        if outcome.status != "resolved":
            continue
        binding = bindings.get(outcome.binding_id)
        if binding is None or not binding.collector_id:
            continue
        field = binding.field
        if field is None and outcome.binding_id.startswith("record.identity."):
            field = outcome.binding_id.rsplit(".", 1)[-1]
        if field:
            sources.setdefault(field, set()).add(binding.collector_id)
    return {field: sorted(values) for field, values in sources.items()}
