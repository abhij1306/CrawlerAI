"""Resolver-owned publication policy for extraction surfaces."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from app.core.config import field_mappings
from app.core.config.variant_policy import NON_PUBLIC_VARIANT_IDENTITY_FIELDS
from app.core.records.output_safety import typed_detail_record
from app.extraction.contracts import (
    CanonicalizationTrace,
    CommerceDetailProjection,
    CommerceDetailRecord,
    CommerceListingProjection,
    CommerceListingRecord,
    Decision,
    DerivedFact,
    Evidence,
    JobDetailProjection,
    JobDetailRecord,
    JobListingProjection,
    JobListingRecord,
    PublicationEntry,
    ResolutionResult,
    SelectedFact,
)
from app.extraction.result_building import selected_facts as resolved_selected_facts
from app.core.shared.url_utils import public_asset_delivery_url

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


@dataclass(frozen=True, slots=True)
class _CommerceDetailPolicy:
    """Precomputed resolution lookups and price-policy flags for publication."""

    evidence_by_id: dict[str, Evidence]
    derived_by_key: dict[tuple[str, str], DerivedFact]
    target_ids: frozenset[str]
    selected_facts: tuple[SelectedFact, ...]
    selected_by_decision: dict[str, SelectedFact]
    selected_by_entity_fact: dict[tuple[str, str], SelectedFact]
    variant_skus: set[str]
    has_primary_price: bool
    has_child_price: bool
    has_primary_currency: bool

    def disposition(
        self, *, fact_type: str, value: object
    ) -> tuple[Literal["publish", "suppress", "review"], str | None]:
        return _publication_disposition(
            fact_type=fact_type,
            value=value,
            variant_skus=self.variant_skus,
            has_primary_price=self.has_primary_price,
            has_child_price=self.has_child_price,
            has_primary_currency=self.has_primary_currency,
        )


def _commerce_detail_policy(
    resolution: ResolutionResult, evidence: Sequence[Evidence]
) -> _CommerceDetailPolicy:
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
    selected_facts = resolved_selected_facts(resolution.decisions, tuple(evidence))
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
    has_primary_price, has_child_price = _commerce_price_state(
        resolution, resolved_keys
    )
    has_primary_currency = (
        resolution.primary_offer_entity_id,
        field_mappings.OFFER_CURRENCY_FACT_TYPE,
    ) in resolved_keys
    return _CommerceDetailPolicy(
        evidence_by_id=evidence_by_id,
        derived_by_key=derived_by_key,
        target_ids=frozenset(target_ids),
        selected_facts=selected_facts,
        selected_by_decision=selected_by_decision,
        selected_by_entity_fact=selected_by_entity_fact,
        variant_skus=variant_skus,
        has_primary_price=has_primary_price,
        has_child_price=has_child_price,
        has_primary_currency=has_primary_currency,
    )


def _commerce_price_state(
    resolution: ResolutionResult, resolved_keys: set[tuple[str, str]]
) -> tuple[bool, bool]:
    primary_offer_id = resolution.primary_offer_entity_id or ""
    has_primary_price = any(
        (primary_offer_id, fact_type) in resolved_keys for fact_type in _PRICE_FACTS
    )
    has_child_price = any(
        fact_type in _PRICE_FACTS and entity_id != primary_offer_id
        for entity_id, fact_type in resolved_keys
    ) or any(
        row.status == "eligible" and row.values.get("price") not in _EMPTY
        for row in resolution.variant_decisions
    )
    return has_primary_price, has_child_price


def _decision_publication_entry(
    decision: Decision,
    *,
    field: str,
    accepted: Evidence,
    policy: _CommerceDetailPolicy,
) -> PublicationEntry | None:
    """One record-scoped entry from a resolved decision (derived wins over
    selected unless both carry the same value)."""
    disposition, reason = policy.disposition(
        fact_type=decision.fact_type, value=accepted.value
    )
    derived = policy.derived_by_key.get((decision.entity_id, decision.fact_type))
    if derived is not None:
        selected = policy.selected_by_decision.get(decision.decision_id)
        if selected is not None and selected.value == derived.value:
            derived = None
    if derived is not None:
        return PublicationEntry(
            path=f"record.{field}",
            entity_id=decision.entity_id,
            value=derived.value,
            disposition=disposition,
            reason_code=reason,
            derived_fact_id=derived.derived_fact_id,
            rule_id=derived.rule_id,
            evidence_ids=derived.input_evidence_ids,
            collector_ids=_collector_ids(
                derived.input_evidence_ids, policy.evidence_by_id
            ),
        )
    selected = policy.selected_by_decision.get(decision.decision_id)
    if selected is None:
        return None
    return PublicationEntry(
        path=f"record.{field}",
        entity_id=decision.entity_id,
        value=selected.value,
        disposition=disposition,
        reason_code=reason,
        selected_fact_id=selected.selected_fact_id,
        rule_id=selected.rule_id,
        evidence_ids=selected.evidence_ids,
        collector_ids=_collector_ids(selected.evidence_ids, policy.evidence_by_id),
    )


def _scalar_decision_entries(
    resolution: ResolutionResult, policy: _CommerceDetailPolicy
) -> list[PublicationEntry]:
    """Record-scoped entries from resolved decisions on the target entities."""
    entries: list[PublicationEntry] = []
    for decision in resolution.decisions:
        field = PUBLIC_FACT_TO_FIELD.get(decision.fact_type)
        if (
            field is None
            or decision.entity_id not in policy.target_ids
            or decision.status != "resolved"
            or not decision.accepted_evidence_ids
        ):
            continue
        accepted = policy.evidence_by_id.get(decision.accepted_evidence_ids[0])
        if accepted is None:
            continue
        entry = _decision_publication_entry(
            decision, field=field, accepted=accepted, policy=policy
        )
        if entry is not None:
            entries.append(entry)
    return entries


def _derived_backfill_entries(
    resolution: ResolutionResult,
    policy: _CommerceDetailPolicy,
    authorized_paths: set[str],
) -> list[PublicationEntry]:
    """Derived-fact entries for paths no resolved decision already claimed."""
    entries: list[PublicationEntry] = []
    for derived in resolution.derived_facts:
        field = PUBLIC_FACT_TO_FIELD.get(derived.fact_type)
        path = f"record.{field}" if field else ""
        if (
            not field
            or path in authorized_paths
            or derived.entity_id not in policy.target_ids
        ):
            continue
        disposition, reason = policy.disposition(
            fact_type=derived.fact_type, value=derived.value
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
                    derived.input_evidence_ids, policy.evidence_by_id
                ),
            )
        )
        authorized_paths.add(path)
    return entries


def _variant_publication_entries(
    resolution: ResolutionResult, evidence_by_id: dict[str, Evidence]
) -> list[PublicationEntry]:
    """Variant-scoped commercial facts from eligible variant decisions."""
    entries: list[PublicationEntry] = []
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
    return entries


def commerce_detail_projection(
    resolution: ResolutionResult,
    evidence: Sequence[Evidence],
) -> tuple[CommerceDetailProjection, tuple[SelectedFact, ...]]:
    """Authorize scalar ecommerce-detail publication from resolved truth."""

    policy = _commerce_detail_policy(resolution, evidence)
    entries = _scalar_decision_entries(resolution, policy)
    entries.extend(
        _derived_backfill_entries(resolution, policy, {row.path for row in entries})
    )
    entries.extend(_variant_publication_entries(resolution, policy.evidence_by_id))
    asset_entries, emitted_asset_ids, primary_asset_entity_id = _asset_entries(
        resolution, policy.selected_by_entity_fact, policy.evidence_by_id
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
        policy.selected_facts,
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
    selected = resolved_selected_facts(tuple(decisions), tuple(evidence))
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
    selected = resolved_selected_facts(tuple(decisions), tuple(evidence))
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


def serialize_commerce_detail_projection(
    projection: CommerceDetailProjection,
    *,
    fallback_url: str = "",
) -> CommerceDetailRecord:
    """Serialize only values authorized by a commerce-detail projection."""

    (
        record,
        lineages,
        variants,
        variant_lineages,
        assets,
        asset_lineages,
        field_sources,
    ) = _commerce_projection_buckets(projection)

    if not record.get("url") and fallback_url:
        record["url"] = fallback_url
        lineages["url"] = {"reason_code": "unauthorized_capture_url_fallback"}

    _append_projected_variants(record, lineages, projection, variants, variant_lineages)
    _append_projected_assets(record, lineages, projection, assets, asset_lineages)

    if lineages:
        record["_lineage"] = lineages
    if field_sources:
        record["_field_sources"] = field_sources
    return typed_detail_record(record)


def _commerce_projection_buckets(projection: CommerceDetailProjection):
    record: dict[str, object] = {}
    lineages: dict[str, object] = {}
    variants: dict[str, dict[str, object]] = defaultdict(dict)
    variant_lineages: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    assets: dict[str, dict[str, object]] = defaultdict(dict)
    asset_lineages: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    field_sources: dict[str, list[str]] = {}
    for entry in projection.entries:
        if entry.disposition != "publish":
            continue
        match = _PATH.match(entry.path)
        if match is None:
            continue
        scope, entity_id, field = match.groups()
        value = _serialized_value(entry)
        source = _source_lineage(entry)
        if scope == "record":
            record[field] = value
            lineages[field] = source
            if entry.collector_ids:
                field_sources[field] = list(entry.collector_ids)
        elif scope == "variant" and entity_id:
            variants[entity_id][field] = value
            variant_lineages[entity_id][field] = source
        elif scope == "asset" and entity_id:
            assets[entity_id][field] = value
            asset_lineages[entity_id][field] = source
    return (
        record,
        lineages,
        variants,
        variant_lineages,
        assets,
        asset_lineages,
        field_sources,
    )


def _append_projected_variants(
    record: dict[str, object],
    lineages: dict[str, object],
    projection: CommerceDetailProjection,
    variants: dict[str, dict[str, object]],
    variant_lineages: dict[str, dict[str, dict[str, object]]],
) -> None:
    variant_rows: list[dict[str, object]] = []
    variant_sources: list[dict[str, object]] = []
    for entity_id in projection.variant_entity_ids:
        row = variants.get(entity_id)
        if not row:
            continue
        variant_rows.append(row)
        variant_sources.append(
            {"variant_entity_id": entity_id, **variant_lineages[entity_id]}
        )
    if projection.variant_entity_ids:
        record["variant_count"] = len(projection.variant_entity_ids)
    if variant_rows:
        record["variants"] = variant_rows
        lineages["variants"] = variant_sources


def _append_projected_assets(
    record: dict[str, object],
    lineages: dict[str, object],
    projection: CommerceDetailProjection,
    assets: dict[str, dict[str, object]],
    asset_lineages: dict[str, dict[str, dict[str, object]]],
) -> None:
    primary_id = projection.primary_asset_entity_id
    if primary_id and assets.get(primary_id, {}).get("url"):
        record["image_url"] = assets[primary_id]["url"]
        lineages["image_url"] = {
            "asset_entity_id": primary_id,
            **asset_lineages[primary_id].get("url", {}),
        }
    additional_ids = tuple(
        entity_id
        for entity_id in projection.asset_entity_ids
        if entity_id != primary_id and assets.get(entity_id, {}).get("url")
    )
    if additional_ids:
        record["additional_images"] = tuple(
            assets[entity_id]["url"] for entity_id in additional_ids
        )
        lineages["additional_images"] = [
            {"asset_entity_id": entity_id, **asset_lineages[entity_id].get("url", {})}
            for entity_id in additional_ids
        ]


def serialize_commerce_listing_projection(
    projection: CommerceListingProjection,
) -> tuple[CommerceListingRecord, ...]:
    return tuple(
        CommerceListingRecord.model_validate(row)
        for row in _serialize_many_projection(
            projection.record_entity_ids, projection.entries
        )
    )


def serialize_job_listing_projection(
    projection: JobListingProjection,
) -> tuple[JobListingRecord, ...]:
    return tuple(
        JobListingRecord.model_validate(row)
        for row in _serialize_many_projection(
            projection.record_entity_ids, projection.entries
        )
    )


def serialize_job_detail_projection(
    projection: JobDetailProjection,
) -> tuple[JobDetailRecord, ...]:
    if not projection.entries:
        return ()
    record: dict[str, object] = {}
    lineage: dict[str, object] = {}
    for entry in projection.entries:
        if entry.disposition != "publish" or not entry.path.startswith("record."):
            continue
        field = entry.path.removeprefix("record.")
        record[field] = _serialized_value(entry)
        lineage[field] = _source_lineage(entry)
    if lineage:
        record["_lineage"] = lineage
    return (JobDetailRecord.model_validate(record),) if record.get("title") else ()


def _serialize_many_projection(
    entity_ids: tuple[str, ...],
    entries: tuple[PublicationEntry, ...],
) -> tuple[dict[str, object], ...]:
    rows: dict[str, dict[str, object]] = defaultdict(dict)
    lineages: dict[str, dict[str, object]] = defaultdict(dict)
    pattern = re.compile(r"^record\[([^]]+)]\.(.+)$")
    for entry in entries:
        if entry.disposition != "publish":
            continue
        match = pattern.match(entry.path)
        if match is None:
            continue
        entity_id, field = match.groups()
        rows[entity_id][field] = _serialized_value(entry)
        lineages[entity_id][field] = _source_lineage(entry)
    serialized: list[dict[str, object]] = []
    for entity_id in entity_ids:
        row = rows.get(entity_id)
        if not row:
            continue
        row["_lineage"] = lineages[entity_id]
        row["_subject_id"] = entity_id
        serialized.append(row)
    return tuple(serialized)


def _serialized_value(entry: PublicationEntry) -> object:
    if entry.canonicalization is not None:
        return entry.canonicalization.canonical_value
    return entry.value


def _source_lineage(entry: PublicationEntry) -> dict[str, object]:
    source: dict[str, object] = {}
    if entry.selected_fact_id:
        source["selected_fact_id"] = entry.selected_fact_id
    if entry.derived_fact_id:
        source["derived_fact_id"] = entry.derived_fact_id
    if entry.reason_code:
        source["reason_code"] = entry.reason_code
    if entry.rule_id:
        source["rule_id"] = entry.rule_id
    if entry.evidence_ids:
        source["evidence_ids"] = list(entry.evidence_ids)
    if entry.canonicalization is not None:
        source["canonicalizer_id"] = entry.canonicalization.canonicalizer_id
        source["canonicalizer_version"] = entry.canonicalization.canonicalizer_version
    return source
