"""Variant-to-parent aggregation and parent/variant price reconciliation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.config import field_mappings
from app.core.config.extraction_rules import AVAILABILITY_PARENT_ROLLUP_PRECEDENCE
from app.core.config.variant_policy import (
    DETAIL_PARENT_INHERITED_OFFER_FIELDS,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
    DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO,
    PUBLIC_VARIANT_AXIS_FIELDS,
)
from app.extraction.contracts import Decision, DerivedFact, Evidence, VariantDecision
from app.extraction.entities import EntitySet, VariantEntity
from app.extraction.resolution.lineage import (
    _aggregate_fact,
    _derived_lineage,
    _has_parent_inherited_lineage,
    _lineage_evidence_ids,
    _lineage_reference_ids,
    _resolved_value_and_lineage,
)


def _reconcile_variant_prices(
    variant_decisions: tuple[VariantDecision, ...],
    *,
    primary_offer_entity_id: str | None,
    decisions: tuple[Decision, ...],
    derived_facts: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[tuple[VariantDecision, ...], tuple[DerivedFact, ...]]:
    if not primary_offer_entity_id:
        return variant_decisions, ()
    parent_price = _resolved_value_and_lineage(
        primary_offer_entity_id,
        field_mappings.OFFER_PRICE_FACT_TYPE,
        decisions,
        derived_facts,
        evidence_by_id,
    )
    parent_currency = _resolved_value_and_lineage(
        primary_offer_entity_id,
        field_mappings.OFFER_CURRENCY_FACT_TYPE,
        decisions,
        derived_facts,
        evidence_by_id,
    )
    if parent_price is None or parent_currency is None:
        return variant_decisions, ()
    parent_amount = _decimal(parent_price[0])
    if parent_amount is None:
        return variant_decisions, ()

    eligible = tuple(row for row in variant_decisions if row.status == "eligible")
    leaf_ids = {row.variant_entity_id for row in _leaf_variant_decisions(eligible)}
    updated = _drop_leaf_variant_prices_conflicting_parent(
        variant_decisions,
        leaf_ids=leaf_ids,
        parent_amount=parent_amount,
        parent_currency=str(parent_currency[0]),
    )

    eligible = tuple(
        row
        for row in updated
        if row.status == "eligible" and row.variant_entity_id in leaf_ids
    )
    if _has_parent_inherited_lineage(row.lineage.get("price") for row in eligible):
        return tuple(updated), ()
    value = _reconciled_variant_price(parent_amount, eligible)
    if value is None:
        return tuple(updated), ()
    return _apply_reconciled_variant_price(
        updated,
        leaf_ids=leaf_ids,
        value=value,
        parent_price_lineage=parent_price[1],
    )


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _reconciled_variant_price(
    parent_amount: Decimal, eligible: tuple[VariantDecision, ...]
) -> str | None:
    prices = [row.values.get("price") for row in eligible]
    if not prices or any(value in (None, "", [], {}, ()) for value in prices):
        return None
    if len({str(value) for value in prices}) != 1:
        return None
    variant_amount = _decimal(prices[0])
    if variant_amount is None:
        return None
    denominator = max(abs(parent_amount), abs(variant_amount))
    ratio = (
        abs(parent_amount - variant_amount) / denominator
        if denominator
        else Decimal("0")
    )
    if ratio > Decimal(str(DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO)):
        return None
    return format(min(parent_amount, variant_amount), ".2f")


def _apply_reconciled_variant_price(
    updated: tuple[VariantDecision, ...],
    *,
    leaf_ids: set[str],
    value: str,
    parent_price_lineage: object,
) -> tuple[tuple[VariantDecision, ...], tuple[DerivedFact, ...]]:
    reconciliation_facts: list[DerivedFact] = []
    reconciled: list[VariantDecision] = []
    for row in updated:
        if row.status != "eligible" or row.variant_entity_id not in leaf_ids:
            reconciled.append(row)
            continue
        input_lineage = (parent_price_lineage, row.lineage.get("price"))
        fact = _aggregate_fact(
            row.variant_entity_id,
            field_mappings.OFFER_PRICE_FACT_TYPE,
            value,
            _lineage_evidence_ids(input_lineage),
            "near_equal_parent_variant_price_reconciliation",
            input_selected_fact_ids=_lineage_reference_ids(
                input_lineage, "selected_fact_id"
            ),
            input_derived_fact_ids=_lineage_reference_ids(
                input_lineage, "derived_fact_id"
            ),
        )
        values = {**row.values, "price": value}
        lineage = {**row.lineage, "price": _derived_lineage(fact)}
        reconciled.append(row.model_copy(update={"values": values, "lineage": lineage}))
        reconciliation_facts.append(fact)
    return tuple(reconciled), tuple(reconciliation_facts)


def _drop_leaf_variant_prices_conflicting_parent(
    variant_decisions: tuple[VariantDecision, ...],
    *,
    leaf_ids: set[str],
    parent_amount: Decimal,
    parent_currency: str,
) -> tuple[VariantDecision, ...]:
    updated: list[VariantDecision] = []
    for row in variant_decisions:
        if row.variant_entity_id not in leaf_ids:
            updated.append(row)
            continue
        variant_amount = _same_currency_variant_amount(row, parent_currency)
        if variant_amount is None or not _price_scale_conflicts(
            parent_amount, variant_amount
        ):
            updated.append(row)
            continue
        values = dict(row.values)
        lineage = dict(row.lineage)
        values.pop("price", None)
        lineage.pop("price", None)
        updated.append(
            row.model_copy(
                update={
                    "values": values,
                    "lineage": lineage,
                    "reason_code": "variant_price_conflicts_parent",
                }
            )
        )
    return tuple(updated)


def _same_currency_variant_amount(
    row: VariantDecision, parent_currency: str
) -> Decimal | None:
    if str(row.values.get("currency") or "") != parent_currency:
        return None
    try:
        return Decimal(str(row.values.get("price")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _price_scale_conflicts(left: Decimal, right: Decimal) -> bool:
    smaller = min(abs(left), abs(right))
    larger = max(abs(left), abs(right))
    return bool(smaller and larger / smaller >= Decimal("20"))


def _parent_derived_from_variants(
    *,
    primary_offer_entity_id: str | None,
    primary_product_entity_id: str | None,
    variant_decisions: tuple[VariantDecision, ...],
    expected_variant_count: int,
    existing_fact_keys: frozenset[tuple[str, str]],
    selected_variant_ids: frozenset[str] = frozenset(),
) -> tuple[DerivedFact, ...]:
    if not primary_offer_entity_id:
        return ()
    variants = tuple(row for row in variant_decisions if row.status == "eligible")
    leaf_variants = _leaf_variant_decisions(variants)
    out: list[DerivedFact] = []
    out.extend(
        _aggregate_variant_field(
            primary_offer_entity_id,
            "offer.price",
            "price",
            leaf_variants,
            existing_fact_keys=existing_fact_keys,
            selected_variant_ids=selected_variant_ids,
        )
    )
    out.extend(
        _aggregate_variant_field(
            primary_offer_entity_id,
            "offer.currency",
            "currency",
            leaf_variants,
            existing_fact_keys=existing_fact_keys,
        )
    )
    out.extend(
        _aggregate_variant_field(
            primary_offer_entity_id,
            "offer.original_price",
            "original_price",
            leaf_variants,
            existing_fact_keys=existing_fact_keys,
        )
    )
    out.extend(
        _aggregate_variant_availability(
            primary_offer_entity_id,
            variants,
            expected_variant_count=expected_variant_count,
            existing_fact_keys=existing_fact_keys,
        )
    )
    if (
        primary_product_entity_id
        and (
            primary_product_entity_id,
            field_mappings.PRODUCT_SKU_FACT_TYPE,
        )
        not in existing_fact_keys
    ):
        out.extend(_single_variant_sku(primary_product_entity_id, leaf_variants))
    return tuple(out)


def _leaf_variant_decisions(
    variants: tuple[VariantDecision, ...],
) -> tuple[VariantDecision, ...]:
    depths = tuple(
        sum(
            row.values.get(field) not in (None, "", [], {}, ())
            for field in PUBLIC_VARIANT_AXIS_FIELDS
        )
        for row in variants
    )
    maximum = max(depths, default=0)
    if maximum <= 0:
        return variants
    return tuple(
        row for row, depth in zip(variants, depths, strict=False) if depth == maximum
    )


def _aggregate_variant_field(
    entity_id: str,
    fact_type: str,
    public_field: str,
    variants: tuple[VariantDecision, ...],
    *,
    existing_fact_keys: frozenset[tuple[str, str]],
    selected_variant_ids: frozenset[str] = frozenset(),
) -> tuple[DerivedFact, ...]:
    values = [row.values.get(public_field) for row in variants]
    if not values or any(value in (None, "", [], {}, ()) for value in values):
        # Partial prices may publish a bounded range, never a false aggregate.
        if public_field == "price":
            return _aggregate_partial_variant_price(
                entity_id,
                variants,
                existing_fact_keys=existing_fact_keys,
                selected_variant_ids=selected_variant_ids,
            )
        return ()
    lineages = [row.lineage.get(public_field) for row in variants]
    if _has_parent_inherited_lineage(lineages):
        return ()
    unique_values = {str(value) for value in values}
    evidence_ids = _lineage_evidence_ids(lineages)
    selected_fact_ids = _lineage_reference_ids(lineages, "selected_fact_id")
    derived_fact_ids = _lineage_reference_ids(lineages, "derived_fact_id")
    if public_field == "price" and len(unique_values) > 1:
        return _variant_price_range_facts(
            entity_id,
            unique_values,
            existing_fact_keys=existing_fact_keys,
            evidence_ids=evidence_ids,
            selected_fact_ids=selected_fact_ids,
            derived_fact_ids=derived_fact_ids,
        )
    if len(unique_values) != 1:
        return ()
    if (entity_id, fact_type) in existing_fact_keys:
        return ()
    return (
        _aggregate_fact(
            entity_id,
            fact_type,
            values[0],
            evidence_ids,
            "uniform_variant_offer_aggregate",
            input_selected_fact_ids=selected_fact_ids,
            input_derived_fact_ids=derived_fact_ids,
        ),
    )


def _variant_price_range_facts(
    entity_id: str,
    unique_values: set[str],
    *,
    existing_fact_keys: frozenset[tuple[str, str]],
    evidence_ids: tuple[str, ...],
    selected_fact_ids: tuple[str, ...],
    derived_fact_ids: tuple[str, ...],
) -> tuple[DerivedFact, ...]:
    try:
        decimal_values = tuple(Decimal(value) for value in unique_values)
    except (InvalidOperation, TypeError, ValueError):
        return ()
    minimum = format(min(decimal_values), ".2f")
    maximum = format(max(decimal_values), ".2f")
    price = (
        ()
        if (entity_id, "offer.price") in existing_fact_keys
        else (
            _aggregate_fact(
                entity_id,
                "offer.price",
                minimum,
                evidence_ids,
                "minimum_variant_price_aggregate",
                input_selected_fact_ids=selected_fact_ids,
                input_derived_fact_ids=derived_fact_ids,
            ),
        )
    )
    return (
        *price,
        _aggregate_fact(
            entity_id,
            "offer.price_min",
            minimum,
            evidence_ids,
            "minimum_variant_price_aggregate",
            input_selected_fact_ids=selected_fact_ids,
            input_derived_fact_ids=derived_fact_ids,
        ),
        _aggregate_fact(
            entity_id,
            "offer.price_max",
            maximum,
            evidence_ids,
            "maximum_variant_price_aggregate",
            input_selected_fact_ids=selected_fact_ids,
            input_derived_fact_ids=derived_fact_ids,
        ),
    )


def _aggregate_partial_variant_price(
    entity_id: str,
    variants: tuple[VariantDecision, ...],
    *,
    existing_fact_keys: frozenset[tuple[str, str]],
    selected_variant_ids: frozenset[str],
) -> tuple[DerivedFact, ...]:
    """Publish bounded partial prices and an explicitly selected display price."""
    priced = [
        row for row in variants if row.values.get("price") not in (None, "", [], {}, ())
    ]
    lineages = [row.lineage.get("price") for row in priced]
    if not priced or _has_parent_inherited_lineage(lineages):
        return ()
    try:
        decimals = [(Decimal(str(row.values["price"])), row) for row in priced]
    except (InvalidOperation, TypeError, ValueError):
        return ()
    minimum = format(min(value for value, _ in decimals), ".2f")
    maximum = format(max(value for value, _ in decimals), ".2f")
    selected_fact = _selected_variant_price_fact(
        entity_id,
        decimals,
        existing_fact_keys=existing_fact_keys,
        selected_variant_ids=selected_variant_ids,
    )
    ranges = _bounded_variant_price_facts(
        entity_id,
        priced_count=len(priced),
        minimum=minimum,
        maximum=maximum,
        lineages=lineages,
        existing_fact_keys=existing_fact_keys,
    )
    return (*((selected_fact,) if selected_fact else ()), *ranges)


def _selected_variant_price_fact(
    entity_id: str,
    decimals: list[tuple[Decimal, VariantDecision]],
    *,
    existing_fact_keys: frozenset[tuple[str, str]],
    selected_variant_ids: frozenset[str],
) -> DerivedFact | None:
    selected = [
        (value, row)
        for value, row in decimals
        if row.variant_entity_id in selected_variant_ids
    ]
    if not selected or (entity_id, "offer.price") in existing_fact_keys:
        return None
    value, row = selected[0]
    selected_lineage = [row.lineage.get("price")]
    return _aggregate_fact(
        entity_id,
        "offer.price",
        format(value, ".2f"),
        _lineage_evidence_ids(selected_lineage),
        "selected_variant_price",
        input_selected_fact_ids=_lineage_reference_ids(
            selected_lineage, "selected_fact_id"
        ),
        input_derived_fact_ids=_lineage_reference_ids(
            selected_lineage, "derived_fact_id"
        ),
    )


def _bounded_variant_price_facts(
    entity_id: str,
    *,
    priced_count: int,
    minimum: str,
    maximum: str,
    lineages: list[object],
    existing_fact_keys: frozenset[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    if priced_count < 2 or minimum == maximum:
        return ()
    evidence_ids = _lineage_evidence_ids(lineages)
    selected_fact_ids = _lineage_reference_ids(lineages, "selected_fact_id")
    derived_fact_ids = _lineage_reference_ids(lineages, "derived_fact_id")
    return tuple(
        _aggregate_fact(
            entity_id,
            field,
            bound_value,
            evidence_ids,
            "bounded_variant_price_range",
            input_selected_fact_ids=selected_fact_ids,
            input_derived_fact_ids=derived_fact_ids,
        )
        for field, bound_value in (
            ("offer.price_min", minimum),
            ("offer.price_max", maximum),
        )
        if (entity_id, field) not in existing_fact_keys
    )


def _aggregate_variant_availability(
    entity_id: str,
    variants: tuple[VariantDecision, ...],
    *,
    expected_variant_count: int,
    existing_fact_keys: frozenset[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    lineages = tuple(row.lineage.get("availability") for row in variants)
    if len(variants) != expected_variant_count or _has_parent_inherited_lineage(
        lineages
    ):
        return ()
    values = [str(row.values.get("availability") or "") for row in variants]
    if not values or any(
        value not in AVAILABILITY_PARENT_ROLLUP_PRECEDENCE for value in values
    ):
        return ()
    rolled_up = next(
        (state for state in AVAILABILITY_PARENT_ROLLUP_PRECEDENCE if state in values),
        None,
    )
    if rolled_up is None:
        return ()
    return (
        _aggregate_fact(
            entity_id,
            "offer.availability",
            rolled_up,
            _lineage_evidence_ids(lineages),
            "variant_availability_aggregate",
            input_selected_fact_ids=_lineage_reference_ids(
                lineages, "selected_fact_id"
            ),
            input_derived_fact_ids=_lineage_reference_ids(lineages, "derived_fact_id"),
        ),
    )


def _single_variant_sku(
    entity_id: str,
    variants: tuple[VariantDecision, ...],
) -> tuple[DerivedFact, ...]:
    if len(variants) != 1:
        return ()
    sku = variants[0].values.get("sku")
    if sku in (None, "", [], {}, ()):
        return ()
    return (
        _aggregate_fact(
            entity_id,
            "product.sku",
            sku,
            _lineage_evidence_ids((variants[0].lineage.get("sku"),)),
            "single_variant_sku_to_parent",
            input_selected_fact_ids=_lineage_reference_ids(
                (variants[0].lineage.get("sku"),), "selected_fact_id"
            ),
            input_derived_fact_ids=_lineage_reference_ids(
                (variants[0].lineage.get("sku"),), "derived_fact_id"
            ),
        ),
    )


def _inherit_variant_offer_facts(
    entities: EntitySet,
    decisions: tuple[Decision, ...],
    derived_facts: tuple[DerivedFact, ...],
    *,
    primary_offer_entity_id: str | None,
    evidence_by_id: dict[str, Evidence],
) -> tuple[DerivedFact, ...]:
    facts = tuple(f"offer.{field}" for field in DETAIL_PARENT_INHERITED_OFFER_FIELDS)
    resolved = {
        (item.entity_id, item.fact_type): item
        for item in decisions
        if item.status == "resolved"
    }
    parent = next(
        (
            offer
            for offer in entities.offers
            if offer.entity_id == primary_offer_entity_id
            and offer.variant_entity_id is None
        ),
        None,
    )
    if parent is None:
        return ()
    direct = _direct_variant_offer_facts(entities, facts, resolved)
    inherited: list[DerivedFact] = []
    for variant in entities.variants:
        if not _variant_can_inherit_offer(variant, resolved):
            continue
        for fact_type in facts:
            inherited_fact = _inherited_variant_offer_fact(
                variant.entity_id,
                fact_type,
                parent_entity_id=parent.entity_id,
                direct=direct,
                decisions=decisions,
                derived_facts=derived_facts,
                evidence_by_id=evidence_by_id,
            )
            if inherited_fact is not None:
                inherited.append(inherited_fact)
    return tuple(inherited)


def _direct_variant_offer_facts(
    entities: EntitySet,
    facts: tuple[str, ...],
    resolved: dict[tuple[str, str], Decision],
) -> set[tuple[str, str]]:
    return {
        (offer.variant_entity_id, fact)
        for offer in entities.offers
        if offer.variant_entity_id
        for fact in facts
        if (offer.entity_id, fact) in resolved
    } | {
        (variant.entity_id, fact)
        for variant in entities.variants
        for fact in facts
        if (variant.entity_id, fact) in resolved
    }


def _variant_can_inherit_offer(
    variant: VariantEntity, resolved: dict[tuple[str, str], Decision]
) -> bool:
    return bool(
        variant.option_values
        or variant.identity_key.startswith(("sku:", "gtin:"))
        or (variant.entity_id, "variant.sku") in resolved
    )


def _inherited_variant_offer_fact(
    variant_entity_id: str,
    fact_type: str,
    *,
    parent_entity_id: str,
    direct: set[tuple[str, str]],
    decisions: tuple[Decision, ...],
    derived_facts: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> DerivedFact | None:
    if (variant_entity_id, fact_type) in direct:
        return None
    parent_value = _resolved_value_and_lineage(
        parent_entity_id,
        fact_type,
        decisions,
        derived_facts,
        evidence_by_id,
    )
    if parent_value is None:
        return None
    value, parent_lineage = parent_value
    return _aggregate_fact(
        variant_entity_id,
        fact_type,
        value,
        _lineage_evidence_ids((parent_lineage,)),
        DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
        input_selected_fact_ids=_lineage_reference_ids(
            (parent_lineage,), "selected_fact_id"
        ),
        input_derived_fact_ids=_lineage_reference_ids(
            (parent_lineage,), "derived_fact_id"
        ),
    )
