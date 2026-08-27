from __future__ import annotations

from typing import Any

from app.core.config.extraction_price_rules import (
    DETAIL_JSONLD_CURRENCY_FIELDS,
    DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS,
    DETAIL_JSONLD_ORIGINAL_PRICE_TYPES,
    DETAIL_JSONLD_PRICE_FIELDS,
)
from app.core.config.field_mappings import (
    ECOMMERCE_JSONLD_OFFER_FACT_TYPES,
    OFFER_CURRENCY_FACT_TYPE,
    OFFER_ORIGINAL_PRICE_FACT_TYPE,
    OFFER_PRICE_FACT_TYPE,
)
from app.core.records.normalizers import normalize_structured_offer_values
from app.extraction.collectors._helpers import evidence, text_value
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


def offer_fact_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    offer_path: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
) -> list[Evidence]:
    normalized = normalize_structured_offer_values(row)
    return [
        _offer_evidence(
            bundle,
            artifact_id,
            fact,
            value,
            f"{offer_path}/{key}",
            group,
            subject_id,
            hint,
            parent_subject_id,
            parent_scope,
            source_subject_ids,
        )
        for key, fact in ECOMMERCE_JSONLD_OFFER_FACT_TYPES.items()
        if (value := text_value(normalized.get(key)))
    ]


def price_specification_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    specs: Any,
    path: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
) -> list[Evidence]:
    rows = specs if isinstance(specs, list) else [specs]
    out: list[Evidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        price_fact = (
            OFFER_ORIGINAL_PRICE_FACT_TYPE
            if _price_specification_is_original(row)
            else OFFER_PRICE_FACT_TYPE
        )
        mappings = (
            *((key, price_fact) for key in DETAIL_JSONLD_PRICE_FIELDS),
            *(
                (key, OFFER_ORIGINAL_PRICE_FACT_TYPE)
                for key in DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS
            ),
            *((key, OFFER_CURRENCY_FACT_TYPE) for key in DETAIL_JSONLD_CURRENCY_FIELDS),
        )
        out.extend(
            _mapped_specification_evidence(
                bundle,
                artifact_id,
                row,
                f"{path}/{index}",
                group,
                subject_id,
                hint,
                parent_subject_id,
                parent_scope,
                source_subject_ids,
                mappings=mappings,
            )
        )
    return out


def _mapped_specification_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    row: dict[str, Any],
    path: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
    *,
    mappings: tuple[tuple[str, str], ...],
) -> list[Evidence]:
    return [
        _offer_evidence(
            bundle,
            artifact_id,
            fact,
            value,
            f"{path}/{key}",
            group,
            subject_id,
            hint,
            parent_subject_id,
            parent_scope,
            source_subject_ids,
        )
        for key, fact in mappings
        if (value := text_value(row.get(key)))
    ]


def _price_specification_is_original(row: dict[str, Any]) -> bool:
    price_type = text_value(row.get("priceType")).rstrip("/").rsplit("/", 1)[-1]
    return price_type.casefold() in DETAIL_JSONLD_ORIGINAL_PRICE_TYPES


def _offer_evidence(
    bundle: CaptureBundle,
    artifact_id: str,
    fact: str,
    value: str,
    locator: str,
    group: str,
    subject_id: str,
    hint: EntityHint,
    parent_subject_id: str | None,
    parent_scope: str,
    source_subject_ids: tuple[str, ...],
) -> Evidence:
    return evidence(
        bundle,
        artifact_id,
        "jsonld",
        fact,
        value,
        SourceLocator(kind="json_pointer", value=locator),
        group_id=group,
        hint=hint,
        directness="embedded",
        confidence=0.9,
        subject_id=subject_id,
        subject_scope="offer",
        parent_subject_id=parent_subject_id,
        parent_scope=parent_scope,
        source_subject_ids=source_subject_ids,
    )
