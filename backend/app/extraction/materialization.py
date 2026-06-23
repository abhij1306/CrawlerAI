from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.extraction.contracts import (
    AssetDecision,
    CommerceDetailRecord,
    CommerceVariantRecord,
    Decision,
    DerivedFact,
    Evidence,
    ResolutionResult,
)
from app.core.config.extraction_rules import (
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
)
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.core.records.url_identity import detail_title_from_url, semantic_identity_tokens
from app.core.shared.field_coerce import sanitize_option_scalar
from app.extraction.entities import EntitySet, OfferEntity

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
    parent_entity_ids = {
        entity_id
        for entity_id in (
            resolution.primary_product_entity_id,
            resolution.primary_offer_entity_id,
        )
        if entity_id
    }
    for decision in resolution.decisions:
        field = PUBLIC_MAP.get(decision.fact_type)
        if decision.entity_id not in parent_entity_ids:
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
    _recover_unique_same_product_scalars(
        record,
        lineages,
        entities,
        resolution,
        by_id,
        derived,
    )
    _materialize_product_assets(record, lineages, resolution.asset_decisions)
    if not record.get("url"):
        record["url"] = canonical_url
        lineages["url"] = {"rule_id": "canonical_capture_url", "evidence_ids": []}
    variants, variant_lineage = _variants(
        entities,
        resolution,
        by_id,
        product_url=str(record.get("url") or canonical_url),
    )
    if variants:
        record["variants"] = variants
        lineages["variants"] = variant_lineage
        _cohere_parent_offer(
            record,
            lineages,
            variants,
            variant_lineage,
            expected_variant_count=len(entities.variants),
        )
        _cohere_parent_availability(
            record,
            lineages,
            variants,
            variant_lineage,
            expected_variant_count=len(entities.variants),
        )
    _recover_matching_product_offer(
        record,
        lineages,
        entities,
        resolution,
        by_id,
        derived,
    )
    if lineages:
        record["_lineage"] = lineages
    if selector_traces:
        record["_selector_traces"] = selector_traces
    return _typed_detail_record(record)


def _recover_unique_same_product_scalars(
    record: dict[str, object],
    lineages: dict[str, object],
    entities: EntitySet,
    resolution: ResolutionResult,
    by_id: dict[str, Evidence],
    derived: dict[tuple[str, str], DerivedFact],
) -> None:
    primary_product_id = resolution.primary_product_entity_id
    if not primary_product_id:
        return
    product_entity_ids = {product.entity_id for product in entities.products}
    for fact_type, field in PUBLIC_MAP.items():
        if fact_type.startswith("offer."):
            continue
        if record.get(field) not in (None, "", [], {}, ()):
            continue
        allowed_entities = product_entity_ids
        candidates: list[tuple[object, Decision, DerivedFact | None]] = []
        for decision in resolution.decisions:
            if (
                decision.entity_id not in allowed_entities
                or decision.fact_type != fact_type
                or decision.status != "resolved"
                or not decision.accepted_evidence_ids
            ):
                continue
            resolved = derived.get((decision.entity_id, fact_type))
            value = (
                resolved.value
                if resolved is not None
                else by_id[decision.accepted_evidence_ids[0]].value
            )
            if value not in (None, "", [], {}, ()):
                candidates.append((value, decision, resolved))
        unique = {str(value).strip().casefold() for value, _decision, _derived in candidates}
        if len(unique) != 1 or not candidates:
            continue
        value, decision, resolved = candidates[0]
        record[field] = value
        source_lineage = lineage(derived=resolved) if resolved else lineage(decision=decision)
        lineages[field] = {
            **source_lineage,
            "rule_id": "unique_same_product_scalar_recovery",
        }


def _recover_matching_product_offer(
    record: dict[str, object],
    lineages: dict[str, object],
    entities: EntitySet,
    resolution: ResolutionResult,
    by_id: dict[str, Evidence],
    derived: dict[tuple[str, str], DerivedFact],
) -> None:
    selected_title = " ".join(semantic_identity_tokens(str(record.get("title") or "")))
    if not selected_title:
        return
    matching_product_ids: set[str] = set()
    for decision in resolution.decisions:
        if (
            decision.fact_type != "product.title"
            or decision.status != "resolved"
            or not decision.accepted_evidence_ids
        ):
            continue
        candidate_title = " ".join(
            semantic_identity_tokens(
                str(by_id[decision.accepted_evidence_ids[0]].value or "")
            )
        )
        if candidate_title == selected_title:
            matching_product_ids.add(decision.entity_id)
    if resolution.primary_product_entity_id:
        matching_product_ids.add(resolution.primary_product_entity_id)
    eligible_offer_ids = {
        offer.entity_id
        for offer in entities.offers
        if offer.product_entity_id in matching_product_ids
    }
    candidates: dict[str, list[tuple[object, Decision, DerivedFact | None]]] = {
        "offer.price": [],
        "offer.currency": [],
        "offer.availability": [],
    }
    for decision in resolution.decisions:
        if (
            decision.entity_id not in eligible_offer_ids
            or decision.fact_type not in candidates
            or decision.status != "resolved"
            or not decision.accepted_evidence_ids
        ):
            continue
        resolved = derived.get((decision.entity_id, decision.fact_type))
        value = (
            resolved.value
            if resolved is not None
            else by_id[decision.accepted_evidence_ids[0]].value
        )
        if value not in (None, "", [], {}, ()):
            candidates[decision.fact_type].append((value, decision, resolved))
    _recover_offer_scalar(
        record,
        lineages,
        "currency",
        candidates["offer.currency"],
    )
    _recover_offer_availability(
        record,
        lineages,
        candidates["offer.availability"],
    )
    _recover_offer_prices(record, lineages, candidates["offer.price"])


def _recover_offer_scalar(
    record: dict[str, object],
    lineages: dict[str, object],
    field: str,
    candidates: list[tuple[object, Decision, DerivedFact | None]],
) -> None:
    if record.get(field) not in (None, "", [], {}, ()) or not candidates:
        return
    unique = {str(value).strip() for value, _decision, _derived in candidates}
    if len(unique) != 1:
        return
    value, decision, resolved = candidates[0]
    source_lineage = lineage(derived=resolved) if resolved else lineage(decision=decision)
    record[field] = value
    lineages[field] = {**source_lineage, "rule_id": "matching_product_offer_recovery"}


def _recover_offer_availability(
    record: dict[str, object],
    lineages: dict[str, object],
    candidates: list[tuple[object, Decision, DerivedFact | None]],
) -> None:
    if record.get("availability") not in (None, "", [], {}, ()) or not candidates:
        return
    values = {str(value) for value, _decision, _derived in candidates}
    if not values <= {"in_stock", "out_of_stock"}:
        return
    value = "in_stock" if "in_stock" in values else "out_of_stock"
    evidence_ids = [
        evidence_id
        for _candidate, decision, resolved in candidates
        for evidence_id in (
            resolved.input_evidence_ids
            if resolved is not None
            else decision.accepted_evidence_ids
        )
    ]
    record["availability"] = value
    lineages["availability"] = {
        "rule_id": "matching_product_availability_aggregate",
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
    }


def _recover_offer_prices(
    record: dict[str, object],
    lineages: dict[str, object],
    candidates: list[tuple[object, Decision, DerivedFact | None]],
) -> None:
    if record.get("price") not in (None, "", [], {}, ()) or not candidates:
        return
    parsed: list[Decimal] = []
    for value, _decision, _derived in candidates:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount > 0:
            parsed.append(amount)
    if not parsed:
        return
    minimum = min(parsed)
    maximum = max(parsed)
    evidence_ids = [
        evidence_id
        for _candidate, decision, resolved in candidates
        for evidence_id in (
            resolved.input_evidence_ids
            if resolved is not None
            else decision.accepted_evidence_ids
        )
    ]
    rule_id = (
        "matching_product_offer_recovery"
        if minimum == maximum
        else "matching_product_price_range_aggregate"
    )
    lineage_value = {
        "rule_id": rule_id,
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
    }
    record["price"] = format(minimum, ".2f")
    lineages["price"] = lineage_value
    if minimum != maximum:
        record["price_min"] = format(minimum, ".2f")
        record["price_max"] = format(maximum, ".2f")
        lineages["price_min"] = lineage_value
        lineages["price_max"] = lineage_value


def _cohere_parent_offer(
    record: dict[str, object],
    lineages: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    *,
    expected_variant_count: int,
) -> None:
    if len(variants) != expected_variant_count:
        return
    for field in ("price", "currency", "original_price"):
        values = [row.get(field) for row in variants]
        if not values or any(value in (None, "", [], {}, ()) for value in values):
            continue
        unique_values = {str(value) for value in values}
        aggregate_value: object = values[0]
        aggregate_rule = "uniform_variant_offer_aggregate"
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
        if parent_value_present and (
            field != "price" or aggregate_rule != "minimum_variant_price_aggregate"
        ):
            continue
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
        if not parent_value_present:
            record[field] = aggregate_value
            lineages[field] = lineage_value
        if field == "price" and record.get("price_min") != record.get("price_max"):
            lineages["price_min"] = lineage_value
            lineages["price_max"] = lineage_value


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
        if current is None or _offer_completeness_rank(offer) > _offer_completeness_rank(
            current
        ):
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
        if _publishable_variant_row(variant, row) and not _variant_url_conflicts(
            product_url, str(row.get("url") or "")
        ):
            rows.append(row)
            lineage_rows.append(lineage_row)
    if len(rows) > 1:
        filtered = [
            (row, lineage_row)
            for row, lineage_row in zip(rows, lineage_rows)
            if _has_variant_option(row)
        ]
        rows = [row for row, _lineage_row in filtered]
        lineage_rows = [lineage_row for _row, lineage_row in filtered]
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


def _variant_url_conflicts(product_url: str, variant_url: str) -> bool:
    if not product_url or not variant_url or product_url == variant_url:
        return False
    product_tokens = set(semantic_identity_tokens(detail_title_from_url(product_url)))
    variant_tokens = set(semantic_identity_tokens(detail_title_from_url(variant_url)))
    if len(product_tokens) < 2 or len(variant_tokens) < 2:
        return False
    overlap_ratio = len(product_tokens & variant_tokens) / min(
        len(product_tokens), len(variant_tokens)
    )
    return overlap_ratio <= VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO


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
    _variant_option_fields(row, lineage_row, variant, decisions, by_id)
    _variant_offer_fields(row, lineage_row, variant, offer, decisions, derived, by_id)
    _variant_asset_field(row, lineage_row, asset, decisions, by_id)
    return row, lineage_row


def _variant_option_fields(
    row: dict[str, object],
    lineage_row: dict[str, object],
    variant,
    decisions,
    by_id,
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
    return order.get(text, 100), text


def _typed_detail_record(record: dict[str, object]) -> CommerceDetailRecord:
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


def _materialize_product_assets(
    record: dict[str, object],
    lineages: dict[str, object],
    asset_decisions: tuple[AssetDecision, ...],
) -> None:
    selected = [
        item for item in asset_decisions if item.url and item.accepted_evidence_ids
    ]
    primary = next((item for item in selected if item.role == "primary"), None)
    if primary is None:
        return
    record["image_url"] = primary.url
    lineages["image_url"] = _asset_lineage(primary)
    primary_url = str(primary.url)
    additional: list[str] = []
    additional_lineage: list[dict[str, object]] = []
    for item in selected:
        if item.role != "additional" or str(item.url) == primary_url:
            continue
        if str(item.url) in additional:
            continue
        additional.append(str(item.url))
        additional_lineage.append(_asset_lineage(item))
    if additional:
        record["additional_images"] = tuple(additional)
        lineages["additional_images"] = additional_lineage


def _asset_lineage(decision: AssetDecision) -> dict[str, object]:
    return {
        "asset_entity_id": decision.asset_entity_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rank": decision.rank,
        "role": decision.role,
        "rule_id": decision.rule_id,
    }
