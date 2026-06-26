from __future__ import annotations

import re

from app.core.config.field_mappings import (
    AVAILABILITY_FIELD,
    BARCODE_FIELD,
    CURRENCY_FIELD,
    IMAGE_URL_FIELD,
    PRICE_FIELD,
    SKU_FIELD,
    STOCK_QUANTITY_FIELD,
    URL_FIELD,
)
from app.core.config.variant_policy import PUBLIC_VARIANT_AXIS_FIELDS
from app.core.records.url_identity import conflicting_product_asset_urls
from app.core.shared.url_utils import public_asset_delivery_url
from app.extraction.contracts import (
    AssetDecision,
    CommerceDetailRecord,
    CommerceVariantRecord,
)


def typed_detail_record(record: dict[str, object]) -> CommerceDetailRecord:
    cleaned = {
        key: value for key, value in record.items() if value not in (None, "", [], {})
    }
    variants = cleaned.get("variants")
    if isinstance(variants, list):
        cleaned["variants"] = tuple(
            CommerceVariantRecord.model_validate(row).model_dump(exclude_none=True)
            for row in variants
            if isinstance(row, dict)
        )
    return CommerceDetailRecord.model_validate(cleaned)


def materialize_product_assets(
    record: dict[str, object],
    lineages: dict[str, object],
    asset_decisions: tuple[AssetDecision, ...],
) -> None:
    selected = [
        item for item in asset_decisions if item.url and item.accepted_evidence_ids
    ]
    product_identity_values = tuple(
        record.get(field)
        for field in (
            "url",
            "canonical_url",
            "title",
            "sku",
            "product_id",
            "part_number",
        )
        if record.get(field) not in (None, "", [], {}, ())
    )
    conflicting_urls = conflicting_product_asset_urls(
        product_identity_values, tuple(str(item.url) for item in selected if item.url)
    )
    style_conflicting_urls = {
        str(item.url)
        for item in selected
        if _asset_style_code_conflicts(product_identity_values, str(item.url))
    }
    filtered = [
        item
        for item in selected
        if str(item.url) not in conflicting_urls
        and str(item.url) not in style_conflicting_urls
    ]
    if filtered:
        selected = filtered
    elif style_conflicting_urls:
        selected = [
            item for item in selected if str(item.url) not in style_conflicting_urls
        ]
    primary = next((item for item in selected if item.role == "primary"), None)
    if primary is None and selected:
        primary = max(
            selected,
            key=lambda item: _asset_identity_match_score(
                product_identity_values, str(item.url)
            ),
        ).model_copy(update={"role": "primary"})
    if primary is None:
        return
    primary_url = public_asset_delivery_url(primary.url)
    if not primary_url:
        return
    record["image_url"] = primary_url
    lineages["image_url"] = _asset_lineage(primary)
    additional: list[str] = []
    additional_lineage: list[dict[str, object]] = []
    for item in selected:
        candidate_url = public_asset_delivery_url(item.url)
        if (
            item.role != "additional"
            or not candidate_url
            or candidate_url == primary_url
        ):
            continue
        if candidate_url in additional:
            continue
        additional.append(candidate_url)
        additional_lineage.append(_asset_lineage(item))
    if additional:
        record["additional_images"] = tuple(additional)
        lineages["additional_images"] = additional_lineage


def _asset_identity_match_score(
    product_values: tuple[object, ...], asset_url: str
) -> tuple[int, int]:
    product_codes = {
        token.casefold()
        for value in product_values
        for token in re.findall(
            r"[A-Za-z]{1,8}\d{2,}[A-Za-z0-9]*(?:-\d{2,4})?",
            str(value or ""),
        )
    }
    normalized_url = re.sub(r"[^a-z0-9]+", "", asset_url.casefold())
    exact_matches = sum(
        re.sub(r"[^a-z0-9]+", "", code) in normalized_url
        for code in product_codes
    )
    return exact_matches, -len(asset_url)


def _asset_style_code_conflicts(
    product_values: tuple[object, ...], asset_url: str
) -> bool:
    product_codes = {
        match.casefold()
        for value in product_values
        for match in re.findall(r"[A-Za-z]{1,8}\d{3,}-\d{2,4}", str(value or ""))
    }
    asset_codes = {
        match.casefold()
        for match in re.findall(r"[A-Za-z]{1,8}\d{3,}-\d{2,4}", asset_url)
    }
    if not product_codes or not asset_codes:
        return False
    product_bases = {code.rsplit("-", 1)[0] for code in product_codes}
    return any(
        code.rsplit("-", 1)[0] in product_bases and code not in product_codes
        for code in asset_codes
    )


def _asset_lineage(decision: AssetDecision) -> dict[str, object]:
    return {
        "asset_entity_id": decision.asset_entity_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rank": decision.rank,
        "role": decision.role,
        "rule_id": decision.rule_id,
    }


def sanitize_materialized_record(
    record: dict[str, object], lineages: dict[str, object]
) -> None:
    if "availability" in record and not public_availability(record.get("availability")):
        record.pop("availability", None)
        lineages.pop("availability", None)

    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    raw_lineage = lineages.get("variants")
    lineage_rows = raw_lineage if isinstance(raw_lineage, list) else []
    rows: list[dict[str, object]] = []
    retained_lineage: list[dict[str, object]] = []
    for index, raw_row in enumerate(variants):
        if not isinstance(raw_row, dict):
            continue
        row = {
            key: value
            for key, value in raw_row.items()
            if value not in (None, "", [], {}, ())
        }
        if "availability" in row and not public_availability(row.get("availability")):
            row.pop("availability", None)
        if not _variant_row_is_actionable(row):
            continue
        rows.append(row)
        lineage = lineage_rows[index] if index < len(lineage_rows) else {}
        retained_lineage.append(
            {field: value for field, value in lineage.items() if field in row}
            if isinstance(lineage, dict)
            else {}
        )

    if rows:
        record["variants"] = rows
        record["variant_count"] = len(rows)
        lineages["variants"] = retained_lineage
        return
    record.pop("variants", None)
    record.pop("variant_count", None)
    lineages.pop("variants", None)


def _variant_row_is_actionable(row: dict[str, object]) -> bool:
    transport_fields = {
        "variant_id",
        SKU_FIELD,
        BARCODE_FIELD,
        URL_FIELD,
        PRICE_FIELD,
        CURRENCY_FIELD,
        IMAGE_URL_FIELD,
        AVAILABILITY_FIELD,
        STOCK_QUANTITY_FIELD,
    }
    if any(row.get(field) not in (None, "", [], {}, ()) for field in transport_fields):
        return True
    axes = {
        key
        for key, value in row.items()
        if key in PUBLIC_VARIANT_AXIS_FIELDS and value not in (None, "", [], {}, ())
    }
    return len(axes) >= 2


def public_availability(value: object) -> str:
    text = str(value or "").strip()
    if text in {
        "in_stock",
        "out_of_stock",
        "limited_stock",
        "preorder",
        "backorder",
        "discontinued",
    }:
        return text
    return ""
