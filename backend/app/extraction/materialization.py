from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse

from app.extraction.contracts import (
    CommerceDetailRecord,
    Decision,
    DerivedFact,
    Evidence,
    ResolutionResult,
)
from app.core.config.extraction_rules import (
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
)
from app.core.config.variant_policy import (
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
    DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO,
)
from app.core.records.url_identity import (
    detail_title_from_url,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce import sanitize_option_scalar
from app.extraction.entities import EntitySet, OfferEntity
from app.core.records.output_safety import (
    materialize_product_assets,
    sanitize_materialized_record,
    typed_detail_record,
)
from app.core.records.variant_drops import VARIANT_DROPS_KEY, VariantDropRecorder
from app.extraction.resolution import inherit_variant_id_from_sku

PUBLIC_MAP = {
    "product.url": "url",
    "product.title": "title",
    "product.brand": "brand",
    "product.description": "description",
    "product.category": "category",
    "product.sku": "sku",
    "product.mpn": "mpn",
    "product.gtin": "gtin",
    "offer.price": "price",
    "offer.currency": "currency",
    "offer.original_price": "original_price",
    "offer.availability": "availability",
}


def lineage(
    decision: Decision | None = None, derived: DerivedFact | None = None
) -> dict[str, object]:
    if derived is not None:
        return {
            "derived_fact_id": derived.derived_fact_id,
            "rule_id": derived.rule_id,
            "evidence_ids": list(derived.input_evidence_ids),
        }
    if decision is None:
        return {}
    return {
        "decision_id": decision.decision_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rule_id": decision.rule_id,
    }


def materialize(
    entities: EntitySet,
    resolution: ResolutionResult,
    evidence: tuple[Evidence, ...],
    *,
    canonical_url: str,
) -> CommerceDetailRecord:
    by_id = {ev.evidence_id: ev for ev in evidence}
    derived = {
        (item.entity_id, item.fact_type): item for item in resolution.derived_facts
    }
    record: dict[str, object] = {}
    lineages: dict[str, object] = {}
    selector_traces: dict[str, object] = {}
    for decision in resolution.decisions:
        field = PUBLIC_MAP.get(decision.fact_type)
        if decision.entity_id not in (
            resolution.primary_product_entity_id,
            resolution.primary_offer_entity_id,
        ):
            continue
        if (
            not field
            or decision.status != "resolved"
            or not decision.accepted_evidence_ids
        ):
            continue
        value = derived.get((decision.entity_id, decision.fact_type))
        accepted = by_id[decision.accepted_evidence_ids[0]]
        record[field] = value.value if value is not None else accepted.value
        lineages[field] = (
            lineage(derived=value) if value else lineage(decision=decision)
        )
        if accepted.locator.kind == "css_selector" and not accepted.metadata.get(
            "derived_by"
        ):
            selector_traces[field] = {
                "selector_kind": "css_selector",
                "selector_value": accepted.locator.value,
                "selector_source": accepted.collector_id,
                "sample_value": accepted.value,
            }
    if not record.get("url"):
        record["url"] = canonical_url
        lineages["url"] = {"rule_id": "canonical_capture_url", "evidence_ids": []}
    materialize_product_assets(record, lineages, resolution.asset_decisions)
    drops = VariantDropRecorder()
    variants, variant_lineage = _variants(
        entities,
        resolution,
        by_id,
        product_url=str(record.get("url") or canonical_url),
        drops=drops,
    )
    if variants:
        record["variant_count"] = len(variants)
        record["variants"] = variants
        lineages["variants"] = variant_lineage
        _cohere_parent_offer(record, lineages, variants, variant_lineage, drops=drops)
        _cohere_parent_availability(
            record,
            lineages,
            variants,
            variant_lineage,
            expected_variant_count=len(entities.variants),
        )
    sanitize_materialized_record(record, lineages, drops=drops)
    if drops.drops:
        record[VARIANT_DROPS_KEY] = [drop.model_dump() for drop in drops.drops]
    field_sources = _field_sources_from_lineage(lineages, by_id)
    if field_sources:
        record["_field_sources"] = field_sources
    if lineages:
        record["_lineage"] = lineages
    if selector_traces:
        record["_selector_traces"] = selector_traces
    return typed_detail_record(record)


def _field_sources_from_lineage(
    lineages: dict[str, object],
    evidence_by_id: dict[str, Evidence],
) -> dict[str, list[str]]:
    sources: dict[str, list[str]] = {}
    for field_name, raw_lineage in lineages.items():
        if not isinstance(raw_lineage, dict):
            continue
        evidence_ids = raw_lineage.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            continue
        collector_ids: list[str] = []
        for evidence_id in evidence_ids:
            evidence = evidence_by_id.get(str(evidence_id))
            collector_id = str(getattr(evidence, "collector_id", "") or "").strip()
            if collector_id and collector_id not in collector_ids:
                collector_ids.append(collector_id)
        if collector_ids:
            sources[field_name] = collector_ids
    if "url" in lineages and "url" not in sources:
        sources["url"] = ["url"]
    return sources


def _cohere_parent_offer(
    record: dict[str, object],
    lineages: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    *,
    drops: VariantDropRecorder,
) -> None:
    variants, variant_lineage = _leaf_variant_rows(variants, variant_lineage)
    _drop_conflicting_variant_prices(record, variants, variant_lineage, drops=drops)
    variant_skus = {
        str(row.get("sku"))
        for row in variants
        if row.get("sku") not in (None, "", [], {}, ())
    }
    if len(variant_skus) > 1 and str(record.get("sku") or "") in variant_skus:
        record.pop("sku", None)
        lineages.pop("sku", None)
    for field in ("price", "currency", "original_price", "sku"):
        values = [row.get(field) for row in variants]
        if (
            (field == "sku" and len(variants) != 1)
            or not values
            or any(value in (None, "", [], {}, ()) for value in values)
        ):
            continue
        unique_values = {str(value) for value in values}
        aggregate_value: object = values[0]
        aggregate_rule = (
            "single_variant_sku_to_parent"
            if field == "sku"
            else "uniform_variant_offer_aggregate"
        )
        if len(unique_values) != 1:
            if field != "price":
                continue
            try:
                decimal_values = tuple(Decimal(value) for value in unique_values)
                minimum = min(decimal_values)
                maximum = max(decimal_values)
            except (InvalidOperation, TypeError, ValueError):
                continue
            aggregate_value = format(minimum, ".2f")
            record["price_min"] = format(minimum, ".2f")
            record["price_max"] = format(maximum, ".2f")
            aggregate_rule = "minimum_variant_price_aggregate"
        parent_value_present = record.get(field) not in (None, "", [], {}, ())
        if field == "price" and parent_value_present and len(unique_values) == 1:
            aggregate_value = _reconcile_near_equal_price(
                record, lineages, variants, variant_lineage, aggregate_value
            )
            unique_values = {str(aggregate_value)}
        field_lineage = [row.get(field) for row in variant_lineage]
        if any(
            isinstance(item, dict)
            and item.get("rule_id") == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
            for item in field_lineage
        ):
            continue
        evidence_ids = tuple(
            str(evidence_id)
            for item in field_lineage
            for evidence_id in _lineage_evidence_ids(item)
        )
        lineage_value = {
            "rule_id": aggregate_rule,
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
        }
        if field == "price" and record.get("price_min") != record.get("price_max"):
            lineages["price_min"] = lineage_value
            lineages["price_max"] = lineage_value
        if parent_value_present and (len(variants) < 2 or len(unique_values) != 1):
            continue
        record[field] = aggregate_value
        lineages[field] = lineage_value


def _drop_conflicting_variant_prices(
    record: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    *,
    drops: VariantDropRecorder,
) -> None:
    parent_price = record.get("price")
    parent_currency = str(record.get("currency") or "")
    if parent_price in (None, "", [], {}, ()) or not parent_currency:
        return
    try:
        parent_amount = Decimal(str(parent_price))
    except (InvalidOperation, TypeError, ValueError):
        return
    for row, lineage_row in zip(variants, variant_lineage):
        if str(row.get("currency") or "") != parent_currency:
            continue
        try:
            variant_amount = Decimal(str(row.get("price")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        smaller = min(abs(parent_amount), abs(variant_amount))
        larger = max(abs(parent_amount), abs(variant_amount))
        if smaller and larger / smaller >= Decimal("20"):
            drops.record(
                row,
                stage="materialize",
                rule="variant_price_conflicts_parent",
                reason=f"variant price diverges ≥20x from parent {parent_price}",
            )
            row.pop("price", None)
            lineage_row.pop("price", None)


def _reconcile_near_equal_price(
    record: dict[str, object],
    lineages: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    aggregate_value: object,
) -> object:
    if any(
        isinstance(item := row.get("price"), dict)
        and item.get("rule_id") == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        for row in variant_lineage
    ):
        return aggregate_value
    try:
        parent_amount = Decimal(str(record["price"]))
        variant_amount = Decimal(str(aggregate_value))
        denominator = max(abs(parent_amount), abs(variant_amount))
        ratio = (
            abs(parent_amount - variant_amount) / denominator
            if denominator
            else Decimal("0")
        )
    except (InvalidOperation, TypeError, ValueError):
        return aggregate_value
    if ratio > Decimal(str(DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO)):
        return aggregate_value
    value = format(min(parent_amount, variant_amount), ".2f")
    evidence_ids = list(_lineage_evidence_ids(lineages.get("price")))
    for row, lineage_row in zip(variants, variant_lineage):
        evidence_ids.extend(_lineage_evidence_ids(lineage_row.get("price")))
        row["price"] = value
        lineage_row["price"] = {
            "rule_id": "near_equal_parent_variant_price_reconciliation",
            "evidence_ids": list(dict.fromkeys(evidence_ids)),
        }
    return value


def _leaf_variant_rows(
    variants: list[dict[str, object]],
    lineage: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    # Aggregation-scope filter only: callers use the returned subset to compute
    # parent-offer coherence, not to mutate the published variant list, so no
    # drop is recorded here (the rows still ship in ``record["variants"]``).
    option_fields = ("color", "size", "style", "material", "gender")
    depths = [
        sum(row.get(field) not in (None, "", [], {}, ()) for field in option_fields)
        for row in variants
    ]
    maximum = max(depths, default=0)
    if maximum <= 0:
        return variants, lineage
    selected = [
        (row, lineage_row)
        for row, lineage_row, depth in zip(variants, lineage, depths)
        if depth == maximum
    ]
    return [row for row, _ in selected], [row for _, row in selected]


def _cohere_parent_availability(
    record: dict[str, object],
    lineages: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    *,
    expected_variant_count: int,
) -> None:
    if len(variants) != expected_variant_count or any(
        isinstance(availability_lineage := row.get("availability"), dict)
        and availability_lineage.get("rule_id")
        == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        for row in variant_lineage
    ):
        return
    availability = [str(row.get("availability") or "") for row in variants]
    if not availability or any(
        value not in {"in_stock", "out_of_stock"} for value in availability
    ):
        return
    evidence_ids = tuple(
        str(evidence_id)
        for row in variant_lineage
        for evidence_id in _lineage_evidence_ids(row.get("availability"))
    )
    record["availability"] = (
        "in_stock" if "in_stock" in availability else "out_of_stock"
    )
    lineages["availability"] = {
        "rule_id": "variant_availability_aggregate",
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
    }


def _lineage_evidence_ids(value: object) -> tuple[object, ...]:
    if not isinstance(value, dict):
        return ()
    evidence_ids = value.get("evidence_ids")
    if isinstance(evidence_ids, (list, tuple)):
        return tuple(evidence_ids)
    return ()


def _variants(
    entities: EntitySet,
    resolution: ResolutionResult,
    by_id: dict[str, Evidence],
    *,
    product_url: str,
    drops: VariantDropRecorder,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    decisions = {
        (d.entity_id, d.fact_type): d
        for d in resolution.decisions
        if d.status == "resolved"
    }
    derived = {
        (item.entity_id, item.fact_type): item for item in resolution.derived_facts
    }
    rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    offer_by_variant: dict[str, OfferEntity] = {}
    for offer in entities.offers:
        if not offer.variant_entity_id:
            continue
        current = offer_by_variant.get(offer.variant_entity_id)
        if current is None or _offer_completeness_rank(
            offer
        ) > _offer_completeness_rank(current):
            offer_by_variant[offer.variant_entity_id] = offer
    asset_by_variant = {
        asset.variant_entity_id: asset
        for asset in entities.assets
        if asset.variant_entity_id
    }
    for variant in entities.variants:
        row, lineage_row = _variant_public_row(
            variant,
            decisions,
            derived,
            by_id,
            offer_by_variant.get(variant.entity_id),
            asset_by_variant.get(variant.entity_id),
        )
        if not _publishable_variant_row(variant, row):
            drops.record(
                row,
                stage="materialize",
                rule="variant_not_publishable",
                reason="no option axis or identity+commercial fact",
            )
            continue
        if _variant_url_conflicts(product_url, str(row.get("url") or ""), row):
            drops.record(
                row,
                stage="materialize",
                rule="variant_url_conflicts_product",
                reason="variant url resolves to a different product",
            )
            continue
        rows.append(row)
        lineage_rows.append(lineage_row)
    if len(rows) > 1:
        kept: list[tuple[dict[str, object], dict[str, object]]] = []
        for row, lineage_row in zip(rows, lineage_rows):
            if _has_variant_option(row):
                kept.append((row, lineage_row))
            else:
                drops.record(
                    row,
                    stage="materialize",
                    rule="optionless_variant_among_options",
                    reason="row has no option axis while siblings do",
                )
        rows = [row for row, _lineage_row in kept]
        lineage_rows = [lineage_row for _row, lineage_row in kept]
    ordered = sorted(
        zip(rows, lineage_rows),
        key=lambda item: (
            str(item[0].get("color") or ""),
            _size_sort_key(item[0].get("size")),
            str(item[0].get("sku") or ""),
            str(item[0].get("url") or ""),
        ),
    )
    return [row for row, _ in ordered], [item for _, item in ordered]


def _offer_completeness_rank(offer) -> tuple[int, int, int, str]:
    fact_evidence = dict(offer.fact_evidence or {})
    commercial_fields = (
        "offer.price",
        "offer.currency",
        "offer.availability",
        "offer.stock_quantity",
    )
    present = sum(bool(fact_evidence.get(field)) for field in commercial_fields)
    evidence_count = sum(len(tuple(ids or ())) for ids in fact_evidence.values())
    has_availability = int(
        bool(fact_evidence.get("offer.availability"))
        or bool(fact_evidence.get("offer.stock_quantity"))
    )
    return has_availability, present, evidence_count, str(offer.entity_id)


def _variant_url_conflicts(
    product_url: str,
    variant_url: str,
    row: dict[str, object],
) -> bool:
    if not product_url or not variant_url or product_url == variant_url:
        return False
    product_tokens = set(semantic_identity_tokens(detail_title_from_url(product_url)))
    variant_tokens = set(semantic_identity_tokens(detail_title_from_url(variant_url)))
    if len(product_tokens) < 2 or len(variant_tokens) < 2:
        return False
    overlap_ratio = len(product_tokens & variant_tokens) / min(
        len(product_tokens), len(variant_tokens)
    )
    if overlap_ratio <= VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO:
        return True
    if urlparse(product_url).path.rstrip("/") == urlparse(variant_url).path.rstrip("/"):
        return False
    option_tokens = {
        token
        for field in ("color", "size", "style", "material", "gender")
        for token in semantic_identity_tokens(str(row.get(field) or ""))
    }
    unexplained = (variant_tokens - product_tokens) - option_tokens
    return bool(unexplained)


def _publishable_variant_row(variant, row: dict[str, object]) -> bool:
    if not variant.identity_key:
        return False
    if _has_variant_option(row):
        return True
    has_explicit_identity = any(
        row.get(field) not in (None, "", [], {}, ())
        for field in ("variant_id", "sku", "gtin", "url")
    )
    return has_explicit_identity and _has_variant_commercial_fact(row)


def _has_variant_option(row: dict[str, object]) -> bool:
    transport_fields = {
        "variant_id",
        "sku",
        "gtin",
        "url",
        "image_url",
        "price",
        "currency",
        "availability",
        "stock_quantity",
    }
    return any(
        key not in transport_fields and value not in (None, "", [], {}, ())
        for key, value in row.items()
    )


def _has_variant_commercial_fact(row: dict[str, object]) -> bool:
    return any(
        row.get(field) not in (None, "", [], {}, ())
        for field in ("price", "availability", "stock_quantity")
    )


def _variant_public_row(
    variant, decisions, derived, by_id, offer, asset
) -> tuple[dict[str, object], dict[str, object]]:
    row: dict[str, object] = {}
    lineage_row: dict[str, object] = {}
    for fact, field in {
        "variant.id": "variant_id",
        "variant.sku": "sku",
        "variant.gtin": "gtin",
        "variant.url": "url",
    }.items():
        decision = decisions.get((variant.entity_id, fact))
        if decision and decision.accepted_evidence_ids:
            row[field] = by_id[decision.accepted_evidence_ids[0]].value
            lineage_row[field] = lineage(decision=decision)
    inherit_variant_id_from_sku(row, lineage_row)
    _variant_option_fields(row, lineage_row, variant, decisions, by_id)
    _variant_offer_fields(row, lineage_row, variant, offer, decisions, derived, by_id)
    _variant_asset_field(row, lineage_row, asset, decisions, by_id)
    return row, lineage_row


def _variant_option_fields(
    row: dict[str, object], lineage_row: dict[str, object], variant, decisions, by_id
) -> None:
    candidates: list[tuple[str, str, Decision]] = []
    for (entity_id, fact_type), decision in decisions.items():
        if (
            entity_id != variant.entity_id
            or not fact_type.startswith("variant.option.")
            or not decision.accepted_evidence_ids
        ):
            continue
        field = fact_type.rsplit(".", 1)[-1]
        value = sanitize_option_scalar(
            field, by_id[decision.accepted_evidence_ids[0]].value
        )
        if value is not None:
            candidates.append((field, value, decision))

    identity_values = {
        str(row.get(field) or "").strip().casefold()
        for field in ("variant_id", "sku", "gtin")
        if str(row.get(field) or "").strip()
    }
    for field, value, decision in candidates:
        normalized = value.casefold()
        if normalized in identity_values:
            continue
        row[field] = value
        lineage_row[field] = lineage(decision=decision)


def _variant_offer_fields(
    row, lineage_row, variant, offer, decisions, derived, by_id
) -> None:
    for fact, field in {
        "offer.price": "price",
        "offer.currency": "currency",
        "offer.original_price": "original_price",
        "offer.availability": "availability",
        "offer.stock_quantity": "stock_quantity",
    }.items():
        decision = decisions.get((offer.entity_id, fact)) if offer else None
        decision = decision or decisions.get((variant.entity_id, fact))
        if not decision or not decision.accepted_evidence_ids:
            continue
        value = derived.get((decision.entity_id, fact))
        row[field] = (
            value.value
            if value is not None
            else by_id[decision.accepted_evidence_ids[0]].value
        )
        lineage_row[field] = (
            lineage(derived=value) if value else lineage(decision=decision)
        )
    if row.get("price") not in (None, "", [], {}, ()) and row.get("currency") in (
        None,
        "",
        [],
        {},
        (),
    ):
        row.pop("price", None)
        row.pop("original_price", None)
        lineage_row.pop("price", None)
        lineage_row.pop("original_price", None)


def _variant_asset_field(row, lineage_row, asset, decisions, by_id) -> None:
    decision = decisions.get((asset.entity_id, "asset.image_url")) if asset else None
    if decision and decision.accepted_evidence_ids:
        row["image_url"] = asset.url
        lineage_row["image_url"] = lineage(decision=decision)


def _size_sort_key(value: object) -> tuple[int, str]:
    text = str(value or "").strip().casefold()
    order = {"xxs": 1, "xs": 2, "s": 3, "m": 4, "l": 5, "xl": 6, "xxl": 7}
    if text in order:
        return order[text], text
    numeric = re.fullmatch(r"\d+(?:\.\d+)?", text)
    if numeric:
        return 50, f"{Decimal(text):020.6f}"
    return 100, text
