from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlsplit

from app.extraction.contracts import (
    AssetDecision,
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    RejectedEvidence,
    ResolutionResult,
    VariantDecision,
)
from app.core.config.extraction_price_rules import (
    DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY,
    DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS,
)
from app.core.config.extraction_rules import (
    AVAILABILITY_CANONICAL_ENUM,
    CURRENCY_SYMBOL_MAP,
    DETAIL_TITLE_MEASUREMENT_FLAG,
    DETAIL_TITLE_REJECTION_FLAGS,
    INVALID_AVAILABILITY_EVIDENCE_FLAG,
    PRODUCT_ASSET_IDENTITY_FACT_TYPES,
    VARIANT_COLOR_BRAND_CONFLICT_FLAG,
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
)
from app.core.config.extraction_rules._images import PRODUCT_ASSET_MAX_COUNT
from app.core.config import field_mappings
from app.core.config.field_mappings import INVALID_SCALAR_TYPE_EVIDENCE_FLAG
from app.core.config.variant_policy import (
    DETAIL_PARENT_INHERITED_OFFER_FIELDS,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
    DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO,
    public_variant_row_is_sellable,
)
from app.core.records.url_identity import (
    conflicting_product_asset_urls,
)
from app.core.shared.url_utils import (
    asset_url_identity,
    is_utility_image_url,
    low_resolution_asset_urls,
)
from app.core.shared.field_coerce import sanitize_option_scalar
from app.core.shared.field_coerce_price import repair_price_unit
from app.core.shared.currency_hints import currency_hint_from_page_url
from app.core.shared.field_coerce_text import (
    infer_brand_from_page_identity,
    infer_brand_from_product_url,
    infer_brand_from_title_host,
    infer_brand_from_title_marker,
)
from app.core.records.url_identity import (
    detail_style_code_from_url,
    detail_title_from_url,
    semantic_identity_tokens,
)
from app.extraction.entities import AssetEntity, EntitySet, OfferEntity, VariantEntity
from app.core.shared.ids import stable_id


def inherit_variant_id_from_sku(
    row: dict[str, object], lineage_row: dict[str, object]
) -> None:
    sku = row.get("sku")
    if row.get("variant_id") not in (None, "", [], {}, ()) or sku in (
        None,
        "",
        [],
        {},
        (),
    ):
        return
    row["variant_id"] = sku
    sku_lineage = lineage_row.get("sku")
    lineage_row["variant_id"] = {
        **(dict(sku_lineage) if isinstance(sku_lineage, Mapping) else {}),
        "rule_id": "variant_id_from_unique_sku",
    }


def resolve(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    findings: tuple[Finding, ...],
    *,
    contract_preferences: Mapping[str, tuple[str, ...]] | None = None,
) -> ResolutionResult:
    preferences = contract_preferences or {}
    by_id = {ev.evidence_id: ev for ev in evidence}
    decisions: list[Decision] = []
    rejected_product_subjects = _url_mismatched_product_subjects(evidence)
    for product in entities.products:
        for fact, ids in sorted(product.attribute_evidence.items()):
            eligible_ids = tuple(
                evidence_id
                for evidence_id in ids
                if by_id[evidence_id].subject_id not in rejected_product_subjects
            )
            decisions.append(
                _resolve_scalar(
                    product.entity_id,
                    fact,
                    eligible_ids,
                    by_id,
                    findings,
                    preferred_evidence_ids=preferences.get(fact, ()),
                )
            )
    for variant in entities.variants:
        decisions.extend(_resolve_variant(variant, by_id, findings))
    for offer in entities.offers:
        decisions.extend(
            _resolve_offer(
                offer,
                by_id,
                findings,
                preferred_evidence_ids=(
                    preferences if offer.variant_entity_id is None else {}
                ),
            )
        )
    primary_product_entity_id = (
        entities.products[0].entity_id if len(entities.products) == 1 else None
    )
    primary_offer_entity_id = _preferred_parent_offer_id(entities, decisions, by_id)
    if (
        primary_offer_entity_id is None
        and primary_product_entity_id
        and entities.variants
    ):
        primary_offer_entity_id = stable_id(
            "offer", primary_product_entity_id, "variant_aggregate"
        )
    for asset in entities.assets:
        decisions.append(_resolve_asset(asset, by_id, findings))
    resolved = {
        decision.fact_type for decision in decisions if decision.status == "resolved"
    }
    required = {"product.url", field_mappings.PRODUCT_TITLE_FACT_TYPE}
    asset_urls = tuple(
        str(by_id[evidence_id].value)
        for asset in entities.assets
        for evidence_id in asset.url_evidence_ids
        if evidence_id in by_id
    )
    conflicting_urls = frozenset(
        _normalized_asset_url(value)
        for value in conflicting_product_asset_urls(
            tuple(
                ev.value
                for ev in evidence
                if ev.fact_type in PRODUCT_ASSET_IDENTITY_FACT_TYPES
            ),
            asset_urls,
        )
    )
    low_resolution_urls = frozenset(
        _normalized_asset_url(value) for value in low_resolution_asset_urls(asset_urls)
    )
    derived_facts = _derived(
        decisions,
        by_id,
        page_url=_resolved_product_url(decisions, by_id),
    )
    derived_facts = (
        *derived_facts,
        *_price_unit_derived_facts(
            tuple(decisions),
            by_id,
            _price_unit_repairs(evidence, entities),
        ),
    )
    derived_facts = (
        *derived_facts,
        *_inherit_variant_offer_facts(
            entities,
            tuple(decisions),
            derived_facts,
            primary_offer_entity_id=primary_offer_entity_id,
            evidence_by_id=by_id,
        ),
    )
    variant_decisions = _resolve_variants(entities, decisions, derived_facts, by_id)
    variant_decisions, reconciliation_facts = _reconcile_variant_prices(
        variant_decisions,
        primary_offer_entity_id=primary_offer_entity_id,
        decisions=tuple(decisions),
        derived_facts=derived_facts,
        evidence_by_id=by_id,
    )
    derived_facts = (
        *derived_facts,
        *reconciliation_facts,
        *_parent_derived_from_variants(
            primary_offer_entity_id=primary_offer_entity_id,
            primary_product_entity_id=primary_product_entity_id,
            variant_decisions=variant_decisions,
            expected_variant_count=len(entities.variants),
            existing_fact_keys=frozenset(
                (
                    *(
                        (row.entity_id, row.fact_type)
                        for row in decisions
                        if row.status == "resolved"
                    ),
                    *(
                        (row.entity_id, row.fact_type)
                        for row in (*derived_facts, *reconciliation_facts)
                    ),
                )
            ),
        ),
    )
    asset_decisions = _resolve_product_assets(
        entities.assets,
        by_id,
        conflicting_urls,
        low_resolution_urls,
    )
    derived_facts = (
        *derived_facts,
        *_asset_publication_facts(asset_decisions, tuple(decisions)),
    )
    return ResolutionResult(
        primary_product_entity_id=primary_product_entity_id,
        primary_offer_entity_id=primary_offer_entity_id,
        decisions=tuple(decisions),
        asset_decisions=asset_decisions,
        variant_decisions=variant_decisions,
        derived_facts=derived_facts,
        unresolved_fact_types=tuple(sorted(required - resolved)),
        blocking_finding_ids=tuple(
            sorted(f.finding_id for f in findings if f.blocking)
        ),
    )


def _price_unit_repairs(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> dict[str, tuple[object, str, tuple[str, ...]]]:
    by_id = {row.evidence_id: row for row in evidence}
    offer_by_evidence = {
        evidence_id: offer
        for offer in entities.offers
        for ids in offer.fact_evidence.values()
        for evidence_id in ids
    }
    currency_rows_by_offer = {
        offer.entity_id: tuple(
            by_id[evidence_id]
            for evidence_id in offer.fact_evidence.get(
                field_mappings.OFFER_CURRENCY_FACT_TYPE, ()
            )
            if evidence_id in by_id
            and "invalid_currency" not in by_id[evidence_id].flags
        )
        for offer in entities.offers
    }
    product_currency_rows = {
        product.entity_id: tuple(
            row
            for offer in entities.offers
            if offer.product_entity_id == product.entity_id
            for row in currency_rows_by_offer.get(offer.entity_id, ())
        )
        for product in entities.products
    }
    price_rows = tuple(
        row
        for row in evidence
        if row.fact_type
        in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
        }
    )
    currency_by_evidence: dict[str, str] = {}
    for row in price_rows:
        offer = offer_by_evidence.get(row.evidence_id)
        if offer is None:
            continue
        currency = _preferred_price_currency(
            currency_rows_by_offer.get(offer.entity_id, ())
        ) or _preferred_price_currency(
            product_currency_rows.get(offer.product_entity_id, ())
        )
        if currency:
            currency_by_evidence[row.evidence_id] = currency
    peer_values: dict[str, object] = {}
    for row in price_rows:
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency_by_evidence.get(row.evidence_id, ""),
        )
        peer_values[row.evidence_id] = repaired[0] if repaired else row.value
    repairs: dict[str, tuple[object, str, tuple[str, ...]]] = {}
    for row in price_rows:
        offer = offer_by_evidence.get(row.evidence_id)
        currency = currency_by_evidence.get(row.evidence_id)
        if offer is None or currency is None:
            continue
        peers = tuple(
            other
            for other in price_rows
            if other.evidence_id != row.evidence_id
            and other.fact_type == row.fact_type
            and (
                (
                    (other_offer := offer_by_evidence.get(other.evidence_id))
                    is not None
                    and other_offer.product_entity_id == offer.product_entity_id
                    and (
                        other.collector_id != row.collector_id
                        or other_offer.entity_id == offer.entity_id
                    )
                )
                or (
                    offer_by_evidence.get(other.evidence_id) is None
                    and other.collector_id in DETAIL_PRICE_PAGE_CORROBORATION_COLLECTORS
                    and "invalid_decimal" not in other.flags
                )
            )
        )
        repaired = repair_price_unit(
            row.value,
            source_key=row.locator.value,
            currency=currency,
            corroborating_values=tuple(
                peer_values[other.evidence_id] for other in peers
            ),
        )
        if repaired is not None:
            value, rule_id = repaired
            repairs[row.evidence_id] = (
                value,
                rule_id,
                tuple(other.evidence_id for other in peers),
            )
    return repairs


def _price_unit_derived_facts(
    decisions: tuple[Decision, ...],
    evidence_by_id: dict[str, Evidence],
    repairs: dict[str, tuple[object, str, tuple[str, ...]]],
) -> tuple[DerivedFact, ...]:
    facts: list[DerivedFact] = []
    for decision in decisions:
        if not decision.accepted_evidence_ids:
            continue
        evidence_id = decision.accepted_evidence_ids[0]
        repaired = repairs.get(evidence_id)
        evidence = evidence_by_id.get(evidence_id)
        if repaired is None or evidence is None or repaired[0] == evidence.value:
            continue
        value, rule_id, peer_ids = repaired
        facts.append(
            DerivedFact(
                derived_fact_id=stable_id(
                    "derived", rule_id, decision.entity_id, decision.fact_type, value
                ),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=tuple(dict.fromkeys((evidence_id, *peer_ids))),
                input_selected_fact_ids=(stable_id("selected", decision.decision_id),),
                rule_id=rule_id,
            )
        )
    return tuple(facts)


def _preferred_price_currency(rows: tuple[Evidence, ...]) -> str | None:
    priority = {
        collector_id: index
        for index, collector_id in enumerate(DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY)
    }
    valid = tuple(
        row
        for row in rows
        if str(row.value or "").strip() and "invalid_currency" not in row.flags
    )
    if not valid:
        return None
    best_rank = min(priority.get(row.collector_id, len(priority)) for row in valid)
    values = {
        str(row.value).strip().upper()
        for row in valid
        if priority.get(row.collector_id, len(priority)) == best_rank
    }
    return next(iter(values)) if len(values) == 1 else None


def _asset_publication_facts(
    asset_decisions: tuple[AssetDecision, ...],
    decisions: tuple[Decision, ...],
) -> tuple[DerivedFact, ...]:
    selected_by_entity = {
        row.entity_id: row
        for row in decisions
        if row.fact_type == field_mappings.ASSET_IMAGE_URL_FACT_TYPE
        and row.status == "resolved"
        and row.accepted_evidence_ids
    }
    facts: list[DerivedFact] = []
    for asset in asset_decisions:
        if (
            not asset.asset_entity_id
            or not asset.url
            or not asset.accepted_evidence_ids
        ):
            continue
        selected = selected_by_entity.get(asset.asset_entity_id)
        selected_fact_ids = (
            (stable_id("selected", selected.decision_id),) if selected else ()
        )
        for fact_type, value in (
            ("asset.inclusion", True),
            ("asset.role", asset.role),
            ("asset.position", asset.rank),
        ):
            facts.append(
                _aggregate_fact(
                    asset.asset_entity_id,
                    fact_type,
                    value,
                    asset.accepted_evidence_ids,
                    asset.rule_id,
                    input_selected_fact_ids=selected_fact_ids,
                )
            )
    return tuple(facts)


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
    try:
        parent_amount = Decimal(str(parent_price[0]))
    except (InvalidOperation, TypeError, ValueError):
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
    prices = [row.values.get("price") for row in eligible]
    if not prices or any(value in (None, "", [], {}, ()) for value in prices):
        return tuple(updated), ()
    if len({str(value) for value in prices}) != 1:
        return tuple(updated), ()
    try:
        variant_amount = Decimal(str(prices[0]))
        denominator = max(abs(parent_amount), abs(variant_amount))
        ratio = (
            abs(parent_amount - variant_amount) / denominator
            if denominator
            else Decimal("0")
        )
    except (InvalidOperation, TypeError, ValueError):
        return tuple(updated), ()
    if ratio > Decimal(str(DETAIL_PARENT_VARIANT_PRICE_DRIFT_MAX_RATIO)):
        return tuple(updated), ()

    value = format(min(parent_amount, variant_amount), ".2f")
    reconciliation_facts: list[DerivedFact] = []
    reconciled: list[VariantDecision] = []
    for row in updated:
        if row.status != "eligible" or row.variant_entity_id not in leaf_ids:
            reconciled.append(row)
            continue
        input_lineage = (parent_price[1], row.lineage.get("price"))
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


def _resolved_value_and_lineage(
    entity_id: str,
    fact_type: str,
    decisions: tuple[Decision, ...],
    derived_facts: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[object, dict[str, object]] | None:
    derived = next(
        (
            row
            for row in reversed(derived_facts)
            if row.entity_id == entity_id and row.fact_type == fact_type
        ),
        None,
    )
    if derived is not None:
        return derived.value, _derived_lineage(derived)
    decision = next(
        (
            row
            for row in decisions
            if row.entity_id == entity_id
            and row.fact_type == fact_type
            and row.status == "resolved"
            and row.accepted_evidence_ids
        ),
        None,
    )
    if decision is None:
        return None
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return None
    return evidence.value, _decision_lineage(decision)


def _parent_derived_from_variants(
    *,
    primary_offer_entity_id: str | None,
    primary_product_entity_id: str | None,
    variant_decisions: tuple[VariantDecision, ...],
    expected_variant_count: int,
    existing_fact_keys: frozenset[tuple[str, str]],
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
    option_fields = ("color", "size", "style", "material", "gender")
    depths = tuple(
        sum(
            row.values.get(field) not in (None, "", [], {}, ())
            for field in option_fields
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
) -> tuple[DerivedFact, ...]:
    values = [row.values.get(public_field) for row in variants]
    if not values or any(value in (None, "", [], {}, ()) for value in values):
        return ()
    lineages = [row.lineage.get(public_field) for row in variants]
    if _has_parent_inherited_lineage(lineages):
        return ()
    unique_values = {str(value) for value in values}
    evidence_ids = _lineage_evidence_ids(lineages)
    selected_fact_ids = _lineage_reference_ids(lineages, "selected_fact_id")
    derived_fact_ids = _lineage_reference_ids(lineages, "derived_fact_id")
    if public_field == "price" and len(unique_values) > 1:
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
                "minimum_variant_price_aggregate",
                input_selected_fact_ids=selected_fact_ids,
                input_derived_fact_ids=derived_fact_ids,
            ),
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


def _aggregate_variant_availability(
    entity_id: str,
    variants: tuple[VariantDecision, ...],
    *,
    expected_variant_count: int,
    existing_fact_keys: frozenset[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    if (entity_id, "offer.availability") in existing_fact_keys:
        return ()
    lineages = tuple(row.lineage.get("availability") for row in variants)
    if len(variants) != expected_variant_count or _has_parent_inherited_lineage(
        lineages
    ):
        return ()
    values = [str(row.values.get("availability") or "") for row in variants]
    if not values or any(value not in {"in_stock", "out_of_stock"} for value in values):
        return ()
    return (
        _aggregate_fact(
            entity_id,
            "offer.availability",
            "in_stock" if "in_stock" in values else "out_of_stock",
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


def _aggregate_fact(
    entity_id: str,
    fact_type: str,
    value: object,
    evidence_ids: tuple[str, ...],
    rule_id: str,
    *,
    input_selected_fact_ids: tuple[str, ...] = (),
    input_derived_fact_ids: tuple[str, ...] = (),
) -> DerivedFact:
    return DerivedFact(
        derived_fact_id=stable_id("derived", rule_id, entity_id, fact_type, value),
        entity_id=entity_id,
        fact_type=fact_type,
        value=value,
        input_evidence_ids=evidence_ids,
        input_selected_fact_ids=input_selected_fact_ids,
        input_derived_fact_ids=input_derived_fact_ids,
        rule_id=rule_id,
    )


def _has_parent_inherited_lineage(values) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("rule_id") == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        for item in values
    )


def _lineage_evidence_ids(values) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        evidence_ids = value.get("evidence_ids")
        if not isinstance(evidence_ids, (list, tuple)):
            continue
        out.extend(str(evidence_id) for evidence_id in evidence_ids)
    return tuple(dict.fromkeys(out))


def _lineage_reference_ids(values, key: str) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        reference = value.get(key)
        if reference:
            out.append(str(reference))
    return tuple(dict.fromkeys(out))


def _resolve_variants(
    entities: EntitySet,
    decision_rows: list[Decision],
    derived_rows: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[VariantDecision, ...]:
    decisions = {
        (row.entity_id, row.fact_type): row
        for row in decision_rows
        if row.status == "resolved"
    }
    derived = {(row.entity_id, row.fact_type): row for row in derived_rows}
    offer_by_variant: dict[str, OfferEntity] = {}
    for offer in entities.offers:
        if not offer.variant_entity_id:
            continue
        current = offer_by_variant.get(offer.variant_entity_id)
        if current is None or _offer_rank(offer) > _offer_rank(current):
            offer_by_variant[offer.variant_entity_id] = offer
    asset_by_variant = {
        row.variant_entity_id: row for row in entities.assets if row.variant_entity_id
    }
    product_url = _resolved_product_url(decision_rows, evidence_by_id)
    candidates: list[tuple[VariantEntity, dict[str, object], dict[str, object]]] = []
    rejected: list[VariantDecision] = []
    for variant in entities.variants:
        values, lineage = _resolved_variant_row(
            variant,
            offer_by_variant.get(variant.entity_id),
            asset_by_variant.get(variant.entity_id),
            decisions,
            derived,
            evidence_by_id,
        )
        reason = _variant_rejection_reason(variant, values, product_url)
        if reason:
            rejected.append(
                _variant_decision(variant.entity_id, values, lineage, reason)
            )
        else:
            candidates.append((variant, values, lineage))
    eligible: list[VariantDecision] = []
    for variant, values, lineage in candidates:
        if len(candidates) > 1 and not _has_variant_option(values):
            rejected.append(
                _variant_decision(
                    variant.entity_id,
                    values,
                    lineage,
                    "optionless_variant_among_options",
                )
            )
            continue
        eligible.append(
            VariantDecision(
                variant_entity_id=variant.entity_id,
                status="eligible",
                reason_code="variant_eligible",
                values=values,
                lineage=lineage,
            )
        )
    return tuple((*eligible, *rejected))


def _resolved_variant_row(
    variant: VariantEntity,
    offer: OfferEntity | None,
    asset: AssetEntity | None,
    decisions: dict[tuple[str, str], Decision],
    derived: dict[tuple[str, str], DerivedFact],
    evidence_by_id: dict[str, Evidence],
) -> tuple[dict[str, object], dict[str, object]]:
    values: dict[str, object] = {}
    lineage: dict[str, object] = {}
    for fact, field in {
        "variant.id": "variant_id",
        "variant.sku": "sku",
        "variant.gtin": "gtin",
        "variant.url": "url",
    }.items():
        _put_decision_value(
            values,
            lineage,
            field,
            decisions.get((variant.entity_id, fact)),
            evidence_by_id,
        )
    inherit_variant_id_from_sku(values, lineage)
    _put_variant_options(values, lineage, variant, decisions, evidence_by_id)
    _put_variant_offer(
        values, lineage, variant, offer, decisions, derived, evidence_by_id
    )
    asset_decision = (
        decisions.get((asset.entity_id, "asset.image_url")) if asset else None
    )
    if asset and asset_decision and asset_decision.accepted_evidence_ids:
        values["image_url"] = asset.url
        lineage["image_url"] = _decision_lineage(asset_decision)
    return values, lineage


def _put_decision_value(values, lineage, field, decision, evidence_by_id) -> None:
    if not decision or not decision.accepted_evidence_ids:
        return
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return
    values[field] = evidence.value
    lineage[field] = _decision_lineage(decision)


def _put_variant_options(values, lineage, variant, decisions, evidence_by_id) -> None:
    identity_values = {
        str(values.get(field) or "").strip().casefold()
        for field in ("variant_id", "sku", "gtin")
        if str(values.get(field) or "").strip()
    }
    for (entity_id, fact_type), decision in decisions.items():
        if entity_id != variant.entity_id or not fact_type.startswith(
            "variant.option."
        ):
            continue
        field = fact_type.rsplit(".", 1)[-1]
        evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
        value = sanitize_option_scalar(field, evidence.value) if evidence else None
        if value is None or value.casefold() in identity_values:
            continue
        values[field] = value
        lineage[field] = _decision_lineage(decision)


def _put_variant_offer(
    values, lineage, variant, offer, decisions, derived, evidence_by_id
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
        derived_fact = None
        if offer:
            derived_fact = derived.get((offer.entity_id, fact))
        derived_fact = derived_fact or derived.get((variant.entity_id, fact))
        if (
            not decision or not decision.accepted_evidence_ids
        ) and derived_fact is None:
            continue
        evidence = (
            evidence_by_id.get(decision.accepted_evidence_ids[0])
            if decision and decision.accepted_evidence_ids
            else None
        )
        if derived_fact is None and evidence is None:
            continue
        if derived_fact is not None:
            values[field] = derived_fact.value
            lineage[field] = _derived_lineage(derived_fact)
        elif evidence is not None and decision is not None:
            values[field] = evidence.value
            lineage[field] = _decision_lineage(decision)
    if values.get("price") not in (None, "", [], {}, ()) and values.get("currency") in (
        None,
        "",
        [],
        {},
        (),
    ):
        values.pop("price", None)
        values.pop("original_price", None)
        lineage.pop("price", None)
        lineage.pop("original_price", None)


def _variant_rejection_reason(variant, values, product_url: str) -> str | None:
    if not variant.identity_key:
        return "variant_missing_identity"
    explicit_identity = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("variant_id", "sku", "gtin", "url")
    )
    commercial = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("price", "availability", "stock_quantity")
    )
    if not _has_variant_option(values) and not (explicit_identity and commercial):
        return "variant_not_publishable"
    if not public_variant_row_is_sellable(values):
        return "variant_not_actionable"
    if _variant_url_conflicts(product_url, str(values.get("url") or ""), values):
        return "variant_url_conflicts_product"
    return None


def _variant_url_conflicts(product_url: str, variant_url: str, values) -> bool:
    if not product_url or not variant_url or product_url == variant_url:
        return False
    product_tokens = set(semantic_identity_tokens(detail_title_from_url(product_url)))
    variant_tokens = set(semantic_identity_tokens(detail_title_from_url(variant_url)))
    if len(product_tokens) < 2 or len(variant_tokens) < 2:
        return False
    overlap = len(product_tokens & variant_tokens) / min(
        len(product_tokens), len(variant_tokens)
    )
    if overlap <= VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO:
        return True
    if urlsplit(product_url).path.rstrip("/") == urlsplit(variant_url).path.rstrip("/"):
        return False
    option_tokens = {
        token
        for field in ("color", "size", "style", "material", "gender")
        for token in semantic_identity_tokens(str(values.get(field) or ""))
    }
    return bool((variant_tokens - product_tokens) - option_tokens)


def _has_variant_option(values) -> bool:
    transport = {
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
        key not in transport and value not in (None, "", [], {}, ())
        for key, value in values.items()
    )


def _offer_rank(offer: OfferEntity) -> tuple[int, int, int, str]:
    facts = dict(offer.fact_evidence or {})
    commercial = (
        "offer.price",
        "offer.currency",
        "offer.availability",
        "offer.stock_quantity",
    )
    return (
        int(
            bool(facts.get("offer.availability"))
            or bool(facts.get("offer.stock_quantity"))
        ),
        sum(bool(facts.get(field)) for field in commercial),
        sum(len(tuple(ids or ())) for ids in facts.values()),
        offer.entity_id,
    )


def _resolved_product_url(decisions: list[Decision], evidence_by_id) -> str:
    for decision in decisions:
        if (
            decision.fact_type == "product.url"
            and decision.status == "resolved"
            and decision.accepted_evidence_ids
        ):
            evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
            if evidence:
                return str(evidence.value or "")
    return ""


def _variant_decision(entity_id, values, lineage, reason) -> VariantDecision:
    return VariantDecision(
        variant_entity_id=entity_id,
        status="rejected",
        reason_code=reason,
        values=values,
        lineage=lineage,
    )


def _decision_lineage(decision: Decision) -> dict[str, object]:
    return {
        "decision_id": decision.decision_id,
        "selected_fact_id": stable_id("selected", decision.decision_id),
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rule_id": decision.rule_id,
    }


def _derived_lineage(derived: DerivedFact) -> dict[str, object]:
    return {
        "derived_fact_id": derived.derived_fact_id,
        "evidence_ids": list(derived.input_evidence_ids),
        "rule_id": derived.rule_id,
    }


def _url_mismatched_product_subjects(
    evidence: tuple[Evidence, ...],
) -> frozenset[str]:
    title_flags_by_subject: dict[str, set[str]] = {}
    for row in evidence:
        if (
            row.fact_type != field_mappings.PRODUCT_TITLE_FACT_TYPE
            or not row.subject_id
        ):
            continue
        title_flags_by_subject.setdefault(row.subject_id, set()).update(row.flags)
    return frozenset(
        subject_id
        for subject_id, flags in title_flags_by_subject.items()
        if "title_url_mismatch" in flags and "title_url_match" not in flags
    )


def _resolve_variant(
    variant: VariantEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> tuple[Decision, ...]:
    return tuple(
        _resolve_scalar(variant.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(variant.attribute_evidence.items())
    )


def _resolve_offer(
    offer: OfferEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    *,
    preferred_evidence_ids: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[Decision, ...]:
    # Each offer fact resolves independently. A previous guard blocked
    # price + currency + original_price together when a parent offer was
    # missing either price or currency evidence; that all-or-nothing gate
    # silently dropped real prices whenever currency evidence (often only
    # implicit via host/locale) wasn't collected. Currency inference from
    # the page URL happens downstream in the enrichment layer.
    return tuple(
        _resolve_scalar(
            offer.entity_id,
            fact,
            ids,
            evidence_by_id,
            findings,
            preferred_evidence_ids=(preferred_evidence_ids or {}).get(fact, ()),
        )
        for fact, ids in sorted(offer.fact_evidence.items())
    )


def _preferred_parent_offer_id(
    entities: EntitySet,
    decisions: list[Decision],
    evidence_by_id: dict[str, Evidence],
) -> str | None:
    resolved = {
        (decision.entity_id, decision.fact_type): decision
        for decision in decisions
        if decision.status == "resolved" and decision.accepted_evidence_ids
    }
    source_priority = {
        collector_id: index
        for index, collector_id in enumerate(DETAIL_PRICE_CURRENCY_COLLECTOR_PRIORITY)
    }

    def score(offer: OfferEntity) -> tuple[int, int, int, int, str]:
        price = resolved.get((offer.entity_id, field_mappings.OFFER_PRICE_FACT_TYPE))
        currency = resolved.get(
            (offer.entity_id, field_mappings.OFFER_CURRENCY_FACT_TYPE)
        )
        pair = tuple(
            evidence_by_id[decision.accepted_evidence_ids[0]]
            for decision in (price, currency)
            if decision is not None
            and decision.accepted_evidence_ids[0] in evidence_by_id
        )
        collectors = {row.collector_id for row in pair}
        complete = price is not None and currency is not None
        source_rank = max(
            (
                source_priority.get(row.collector_id, len(source_priority))
                for row in pair
            ),
            default=len(source_priority) + 1,
        )
        resolved_fact_count = sum(
            (offer.entity_id, fact_type) in resolved
            for fact_type in offer.fact_evidence
        )
        return (
            0 if complete else 1,
            0 if len(collectors) == 1 and pair else 1,
            source_rank,
            -resolved_fact_count,
            offer.entity_id,
        )

    parents = tuple(
        offer for offer in entities.offers if offer.variant_entity_id is None
    )
    return min(parents, key=score).entity_id if parents else None


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
    direct = {
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
    inherited: list[DerivedFact] = []
    for variant in entities.variants:
        if not (
            variant.option_values
            or variant.identity_key.startswith(("sku:", "gtin:"))
            or (variant.entity_id, "variant.sku") in resolved
        ):
            continue
        for fact_type in facts:
            if (variant.entity_id, fact_type) in direct:
                continue
            parent_value = _resolved_value_and_lineage(
                parent.entity_id,
                fact_type,
                decisions,
                derived_facts,
                evidence_by_id,
            )
            if parent_value is None:
                continue
            value, parent_lineage = parent_value
            inherited.append(
                _aggregate_fact(
                    variant.entity_id,
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
            )
    return tuple(inherited)


def _resolve_asset(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    # Dangling evidence IDs (referenced by the asset but absent from
    # evidence_by_id) are treated as invalid so the primary-asset rejection
    # path triggers correctly when no usable evidence remains.
    invalid_ids = tuple(
        eid
        for eid in asset.url_evidence_ids
        if eid not in evidence_by_id
        or _invalid_primary_asset_url(evidence_by_id[eid].value)
    )
    valid_ids = tuple(
        eid
        for eid in asset.url_evidence_ids
        if eid in evidence_by_id
        and not _invalid_primary_asset_url(evidence_by_id[eid].value)
    )
    if invalid_ids and not valid_ids:
        return Decision(
            decision_id=stable_id(
                "decision",
                asset.entity_id,
                field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
                asset.url_evidence_ids,
            ),
            entity_id=asset.entity_id,
            fact_type=field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
            accepted_evidence_ids=(),
            rejected=tuple(
                RejectedEvidence(evidence_id=eid, reason="invalid_primary_asset")
                for eid in asset.url_evidence_ids
            ),
            finding_ids=(),
            rule_id="PRIMARY_ASSET_REJECTION",
            status="unresolved",
        )
    return _resolve_scalar(
        asset.entity_id,
        field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
        valid_ids,
        evidence_by_id,
        findings,
    )


def _invalid_primary_asset_url(value: object) -> bool:
    return is_utility_image_url(value)


def _resolve_product_assets(
    assets: tuple[AssetEntity, ...],
    evidence_by_id: dict[str, Evidence],
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> tuple[AssetDecision, ...]:
    ranked = [
        (rank, asset, accepted)
        for asset in assets
        if asset.variant_entity_id is None
        for accepted in [_accepted_asset_evidence(asset, evidence_by_id)]
        for rank in [_asset_rank(asset, accepted)]
    ]
    valid = [
        (rank, asset, accepted)
        for rank, asset, accepted in ranked
        if accepted
        and not _asset_rejection_reasons(
            _resolved_asset_url(accepted),
            conflicting_urls=conflicting_urls,
            low_resolution_urls=low_resolution_urls,
        )
    ]
    valid.sort(key=lambda item: item[0])
    decisions: list[AssetDecision] = []
    seen: set[str] = set()
    for index, (_rank_value, asset, accepted) in enumerate(valid):
        if len(decisions) >= PRODUCT_ASSET_MAX_COUNT:
            break
        if asset.identity_key in seen:
            continue
        seen.add(asset.identity_key)
        decisions.append(
            AssetDecision(
                asset_entity_id=asset.entity_id,
                url=_resolved_asset_url(accepted),
                accepted_evidence_ids=(accepted.evidence_id,),
                role="primary" if not decisions else "additional",
                rank=index,
                rule_id=(
                    "PRODUCT_ASSET_PRIMARY"
                    if not decisions
                    else "PRODUCT_ASSET_ADDITIONAL"
                ),
            )
        )
    rejected = [
        AssetDecision(
            asset_entity_id=asset.entity_id,
            url=_resolved_asset_url(accepted),
            accepted_evidence_ids=(),
            role="rejected",
            rank=len(valid) + index,
            rule_id="PRODUCT_ASSET_REJECT",
            rejection_reasons=_asset_rejection_reasons(
                _resolved_asset_url(accepted),
                conflicting_urls=conflicting_urls,
                low_resolution_urls=low_resolution_urls,
            ),
        )
        for index, (_rank_value, asset, accepted) in enumerate(ranked)
        if accepted
        and _asset_rejection_reasons(
            _resolved_asset_url(accepted),
            conflicting_urls=conflicting_urls,
            low_resolution_urls=low_resolution_urls,
        )
    ]
    return tuple(decisions + rejected)


def _asset_rejection_reasons(
    url: str,
    *,
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if url in conflicting_urls:
        reasons.append("product_identity_conflict")
    if url in low_resolution_urls:
        reasons.append("low_resolution_transform")
    if _invalid_primary_asset_url(url):
        reasons.append("invalid_primary_asset")
    return tuple(reasons)


def _normalized_asset_url(value: object) -> str:
    normalized = asset_url_identity(value)
    return normalized[0] if normalized else str(value)


def _resolved_asset_url(evidence: Evidence) -> str:
    return _normalized_asset_url(evidence.value)


def _accepted_asset_evidence(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
) -> Evidence | None:
    candidates = [
        evidence_by_id[eid] for eid in asset.url_evidence_ids if eid in evidence_by_id
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            int(_invalid_primary_asset_url(row.value)),
            int(urlsplit(str(row.value)).scheme.casefold() != "https"),
            -_asset_requested_dimension(row.value),
            _rank(row),
        ),
    )


def _asset_requested_dimension(value: object) -> int:
    dimension_keys = {"w", "width", "wid", "imwidth", "h", "height", "hei"}
    dimensions = [
        int(raw_value)
        for key, raw_value in parse_qsl(
            urlsplit(str(value or "")).query, keep_blank_values=False
        )
        if key.casefold() in dimension_keys and str(raw_value).isdigit()
    ]
    return max(dimensions, default=0)


def _asset_rank(
    asset: AssetEntity,
    accepted: Evidence | None,
) -> tuple[
    int,
    int,
    int,
    int,
    tuple[object, ...],
    str,
]:
    if accepted is None:
        return (99, 99, 99, 99, (99, 99, 99, 0.0, ""), asset.entity_id)
    # Rank using only the accepted evidence so an asset's global ordering
    # reflects the quality of its chosen URL, not the best of any (possibly
    # rejected) evidence collected for that asset.
    role = _asset_role_rank(str(accepted.value))
    collector_rank = _asset_collector_rank(accepted)
    source_order = _asset_source_order(accepted)
    source_rank = _rank(accepted)
    insecure_scheme = int(urlsplit(str(accepted.value)).scheme.casefold() != "https")
    return (
        role,
        collector_rank,
        source_order,
        insecure_scheme,
        source_rank,
        asset.entity_id,
    )


def _asset_role_rank(url: str) -> int:
    text = str(url or "").casefold()
    if any(token in text for token in ("main", "primary", "hero", "pdp")):
        return 0
    if any(token in text for token in ("product", "detail", "gallery", "diagram")):
        return 1
    return 2


def _asset_source_order(ev: Evidence) -> int:
    for token in reversed(
        str(ev.locator.value or "").replace("[", "/").replace("]", "").split("/")
    ):
        if token.isdigit():
            return int(token)
    return 99


def _asset_collector_rank(ev: Evidence) -> int:
    return {
        "jsonld": 0,
        "opengraph": 1,
        "microdata": 2,
        "dom": 3,
        "css_recipe": 3,
        "js_state": 4,
        "network": 5,
        "url": 6,
    }.get(ev.collector_id, 9)


def _resolve_scalar(
    entity_id: str,
    fact_type: str,
    ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    *,
    preferred_evidence_ids: tuple[str, ...] = (),
) -> Decision:
    candidates = sorted(
        (evidence_by_id[eid] for eid in ids if eid in evidence_by_id), key=_rank
    )
    blocking = {
        eid for finding in findings if finding.blocking for eid in finding.evidence_ids
    }
    admissible = [
        ev
        for ev in candidates
        if ev.evidence_id not in blocking and _invalidity_reason(ev) is None
    ]
    finding_ids = tuple(
        f.finding_id for f in findings if set(f.evidence_ids) & set(ids)
    )
    if not admissible:
        return Decision(
            decision_id=stable_id("decision", entity_id, fact_type, ids),
            entity_id=entity_id,
            fact_type=fact_type,
            accepted_evidence_ids=(),
            # Carry the *specific* invalidity reason (e.g. invalid_currency,
            # non_positive_price) instead of a generic "invalid_value" so
            # diagnose.json explains exactly why every candidate was dropped.
            rejected=tuple(
                RejectedEvidence(
                    evidence_id=ev.evidence_id,
                    reason="blocked_by_finding"
                    if ev.evidence_id in blocking
                    else (_invalidity_reason(ev) or "invalid_value"),
                )
                for ev in candidates
            ),
            finding_ids=finding_ids,
            rule_id="SCALAR_LEXICOGRAPHIC",
            status="unresolved",
        )
    preferred = set(preferred_evidence_ids)
    winner = next(
        (row for row in admissible if row.evidence_id in preferred), admissible[0]
    )
    rule_id = (
        "CONTRACT_PREFERRED_SOURCE"
        if winner.evidence_id in preferred
        else "SCALAR_LEXICOGRAPHIC"
    )
    if fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        rule_id = (
            "TITLE_URL_REVIEW_ONLY"
            if "url_derived_title" in winner.flags
            else "TITLE_SEMANTIC_RANKING"
        )

    def _rejected_reason(ev: Evidence) -> str:
        if ev.evidence_id in blocking:
            return "blocked_by_finding"
        reason = _invalidity_reason(ev)
        if reason is not None:
            return reason
        return (
            "stable_tiebreak"
            if _rank(ev)[:-1] == _rank(winner)[:-1]
            else "lower_confidence"
        )

    return Decision(
        decision_id=stable_id("decision", entity_id, fact_type, winner.evidence_id),
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(winner.evidence_id,),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=ev.evidence_id,
                reason=_rejected_reason(ev),
            )
            for ev in candidates
            if ev.evidence_id != winner.evidence_id
        ),
        finding_ids=finding_ids,
        rule_id=rule_id,
        status="resolved",
    )


def _derived(
    decisions: list[Decision],
    by_id: dict[str, Evidence],
    *,
    page_url: str = "",
) -> tuple[DerivedFact, ...]:
    out: list[DerivedFact] = []
    resolved_fact_keys = {
        (decision.entity_id, decision.fact_type)
        for decision in decisions
        if decision.status == "resolved"
    }
    resolved_values = {
        (decision.entity_id, decision.fact_type): by_id[
            decision.accepted_evidence_ids[0]
        ].value
        for decision in decisions
        if decision.status == "resolved"
        and decision.accepted_evidence_ids
        and decision.accepted_evidence_ids[0] in by_id
    }
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str] = {
        (decision.fact_type, decision.accepted_evidence_ids): stable_id(
            "selected", decision.decision_id
        )
        for decision in decisions
        if decision.status == "resolved"
        and len(decision.accepted_evidence_ids) == 1
        and decision.rule_id != DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
    }
    for decision in decisions:
        out.extend(
            _semantic_derived_facts(
                decision,
                by_id,
                page_url=page_url,
                direct_selected_ids=direct_selected_ids,
                resolved_fact_keys=resolved_fact_keys,
                resolved_values=resolved_values,
            )
        )
        if (
            decision.fact_type
            not in {
                field_mappings.OFFER_PRICE_FACT_TYPE,
                field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
            }
            or not decision.accepted_evidence_ids
        ):
            continue
        ev = by_id[decision.accepted_evidence_ids[0]]
        try:
            value = f"{float(str(ev.value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            continue
        rule_id = (
            decision.rule_id
            if decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
            else "NORMALIZE_MONEY_PRECISION"
        )
        out.append(
            DerivedFact(
                derived_fact_id=stable_id(
                    "derived", rule_id, decision.entity_id, decision.fact_type, value
                ),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=decision.accepted_evidence_ids,
                input_selected_fact_ids=tuple(
                    filter(
                        None,
                        (
                            direct_selected_ids.get(
                                (decision.fact_type, decision.accepted_evidence_ids)
                            ),
                        ),
                    )
                ),
                rule_id=rule_id,
            )
        )
    return tuple(out)


def _semantic_derived_facts(
    decision: Decision,
    by_id: dict[str, Evidence],
    *,
    page_url: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_fact_keys: set[tuple[str, str]],
    resolved_values: dict[tuple[str, str], object],
) -> tuple[DerivedFact, ...]:
    if decision.status != "resolved" or not decision.accepted_evidence_ids:
        return ()
    evidence = by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return ()
    if decision.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        existing_brand = resolved_values.get(
            (decision.entity_id, field_mappings.PRODUCT_BRAND_FACT_TYPE)
        )
        existing_brands = (existing_brand,) if existing_brand else ()
        brand = _brand_from_title(
            evidence.value,
            page_url=page_url,
            evidence_values=tuple(
                row.value
                for row in by_id.values()
                if row.fact_type != field_mappings.PRODUCT_URL_FACT_TYPE
            ),
            existing_brands=existing_brands,
        )
        if brand:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
                    value=brand[0],
                    rule_id=brand[1],
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == field_mappings.PRODUCT_URL_FACT_TYPE
        and (decision.entity_id, field_mappings.PRODUCT_SKU_FACT_TYPE)
        not in resolved_fact_keys
    ):
        sku = detail_style_code_from_url(str(evidence.value or page_url))
        if sku:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.PRODUCT_SKU_FACT_TYPE,
                    value=sku,
                    rule_id="sku_from_url_style_code",
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == field_mappings.OFFER_PRICE_FACT_TYPE
        and (decision.entity_id, field_mappings.OFFER_CURRENCY_FACT_TYPE)
        not in resolved_fact_keys
    ):
        currency = _currency_for_price(evidence, page_url=page_url)
        if currency:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.OFFER_CURRENCY_FACT_TYPE,
                    value=currency[0],
                    rule_id=currency[1],
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == "offer.stock_quantity"
        and (decision.entity_id, field_mappings.OFFER_AVAILABILITY_FACT_TYPE)
        not in resolved_fact_keys
    ):
        availability = _availability_from_stock_quantity(evidence)
        if availability:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
                    value=availability,
                    rule_id="availability_from_stock_quantity",
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    return ()


def _derived_fact(
    decision: Decision,
    *,
    fact_type: str,
    value: object,
    rule_id: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
) -> DerivedFact:
    return DerivedFact(
        derived_fact_id=stable_id(
            "derived",
            rule_id,
            decision.entity_id,
            fact_type,
            value,
        ),
        entity_id=decision.entity_id,
        fact_type=fact_type,
        value=value,
        input_evidence_ids=decision.accepted_evidence_ids,
        input_selected_fact_ids=tuple(
            filter(
                None,
                (
                    direct_selected_ids.get(
                        (decision.fact_type, decision.accepted_evidence_ids)
                    ),
                ),
            )
        ),
        rule_id=rule_id,
    )


def _currency_for_price(evidence: Evidence, *, page_url: str) -> tuple[str, str] | None:
    raw = evidence.raw_value if isinstance(evidence.raw_value, str) else ""
    symbols = {
        str(currency)
        for symbol, currency in CURRENCY_SYMBOL_MAP.items()
        if str(symbol) in raw
    }
    if len(symbols) == 1:
        return symbols.pop(), "currency_from_price_symbol"
    if currency := currency_hint_from_page_url(page_url):
        return currency, "currency_from_page_url_hint"
    return None


def _availability_from_stock_quantity(evidence: Evidence) -> str | None:
    try:
        quantity = Decimal(str(evidence.value).strip())
    except (InvalidOperation, ValueError):
        return None
    return "in_stock" if quantity > 0 else "out_of_stock"


def _brand_from_title(
    title: object,
    *,
    page_url: str,
    evidence_values: tuple[object, ...] = (),
    existing_brands: tuple[object, ...] = (),
) -> tuple[str, str] | None:
    page_identity = infer_brand_from_page_identity(
        url=page_url,
        title=title,
        evidence_values=evidence_values,
        existing_brands=existing_brands,
    )
    if page_identity and all(
        str(page_identity).casefold() != str(value).casefold()
        for value in existing_brands
    ):
        existing = str(existing_brands[0]) if existing_brands else ""
        expands_existing = (
            str(page_identity).casefold().startswith(f"{existing.casefold()} ")
        )
        if existing.isupper() and not expands_existing:
            return None
        return page_identity, "page_identity"
    if existing_brands:
        return None
    for rule_id, value in (
        ("brand_from_title_marker", infer_brand_from_title_marker(title)),
        (
            "brand_from_title_host",
            infer_brand_from_title_host(title=title, url=page_url),
        ),
        (
            "brand_from_product_url",
            infer_brand_from_product_url(url=page_url, title=title),
        ),
    ):
        if value:
            return value, rule_id
    return None


_GENERIC_INVALIDITY_FLAGS = frozenset(
    {
        "ambiguous_page_price",
        "brand_boilerplate",
        "brand_identity_conflict",
        "brand_url",
        "category_as_brand",
        "description_incomplete_ending",
        "description_missing_separator",
        "description_promotional_copy",
        "description_ui_pollution",
        "invalid_decimal",
        "invalid_currency",
        "invalid_brand_scalar",
        INVALID_AVAILABILITY_EVIDENCE_FLAG,
        INVALID_SCALAR_TYPE_EVIDENCE_FLAG,
        "invalid_gtin",
        "non_detail_product_url",
        "product_name_as_brand",
        DETAIL_TITLE_MEASUREMENT_FLAG,
        "placeholder_text",
        "tracking_url",
        VARIANT_COLOR_BRAND_CONFLICT_FLAG,
    }
)


def _invalidity_reason(ev: Evidence) -> str | None:
    """The specific reason a candidate is inadmissible, or ``None`` if valid.

    Returns the concrete flag / rule (e.g. ``invalid_currency``,
    ``non_positive_price``) rather than a bool so ``_resolve_scalar`` can thread
    *why* a captured candidate was rejected into the Decision — and from there
    into diagnose.json's per-field ``reason_codes``.
    """

    if ev.fact_type in {
        field_mappings.OFFER_PRICE_FACT_TYPE,
        field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    } and _non_positive_money(ev.value):
        return "non_positive_price"
    flags = set(ev.flags)
    title_rejections = flags & (DETAIL_TITLE_REJECTION_FLAGS - {"truncated_title"})
    if ev.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE and title_rejections:
        return min(title_rejections)
    description_rejections = flags & {
        "description_truncated_ellipsis",
        "description_truncated_fragment",
    }
    if ev.fact_type == "product.description" and description_rejections:
        return min(description_rejections)
    generic = flags & _GENERIC_INVALIDITY_FLAGS
    if generic:
        return min(generic)
    return None


def _non_positive_money(value: object) -> bool:
    try:
        return Decimal(str(value)) <= 0
    except (InvalidOperation, ValueError):
        return False


_PRICE_FACT_TYPES = frozenset(
    {
        field_mappings.OFFER_PRICE_FACT_TYPE,
        field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    }
)
_GTIN_FACT_TYPES = frozenset(
    {field_mappings.PRODUCT_GTIN_FACT_TYPE, field_mappings.VARIANT_GTIN_FACT_TYPE}
)
_URL_FACT_TYPES = frozenset(
    {field_mappings.PRODUCT_URL_FACT_TYPE, field_mappings.ASSET_IMAGE_URL_FACT_TYPE}
)


def _value_quality(ev: Evidence) -> int:
    """Shape-only quality of a candidate value (lower = better).

    A generic safety net keyed on the value's *intrinsic shape* — never on site
    identity. A value that fails its field's basic format/enum check (malformed
    price, non-ISO-4217 currency, off-enum availability, bad GTIN check digit,
    non-absolute URL) ranks below one that passes, so a clean embedded offer
    outranks a malformed-but-unflagged direct DOM scrape. Among well-formed
    candidates this is a constant ``0`` prefix, so it never perturbs the
    reliability/directness spine; it only breaks shape-quality ties that the
    flag-based admissibility filter did not already catch.
    """

    fact_type = ev.fact_type
    if fact_type in _PRICE_FACT_TYPES:
        return 1 if _non_positive_money(ev.value) or not _parses_money(ev.value) else 0
    if fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE:
        return 0 if _is_iso4217_shape(ev.value) else 1
    if fact_type == field_mappings.OFFER_AVAILABILITY_FACT_TYPE:
        return 0 if _is_canonical_availability(ev.value) else 1
    if fact_type in _GTIN_FACT_TYPES:
        return 0 if _is_valid_gtin(ev.value) else 1
    if fact_type in _URL_FACT_TYPES:
        return 0 if _is_absolute_url(ev.value) else 1
    return 0


def _parses_money(value: object) -> bool:
    try:
        Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return False
    return True


def _is_iso4217_shape(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 3 and text.isalpha()


def _is_canonical_availability(value: object) -> bool:
    text = str(value or "").strip().casefold().replace(" ", "_")
    return text in AVAILABILITY_CANONICAL_ENUM


def _is_absolute_url(value: object) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def _is_valid_gtin(value: object) -> bool:
    digits = str(value or "").strip()
    if len(digits) not in {8, 12, 13, 14} or not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    total = 0
    for index, char in enumerate(reversed(body)):
        weight = 3 if index % 2 == 0 else 1
        total += int(char) * weight
    return (10 - total % 10) % 10 == check


def _rank(ev: Evidence) -> tuple[object, ...]:
    quality = _value_quality(ev)
    directness = {"direct": 0, "embedded": 1, "inferred": 2}.get(ev.directness, 3)
    reliability = {
        "jsonld": 0,
        "microdata": 1,
        "js_state": 2,
        "network": 3,
        "opengraph": 4,
        "dom": 5,
        "css_recipe": 5,
        "url": 6,
    }.get(ev.collector_id, 7)
    if ev.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        pollution = int(
            "seo_title_pollution" in ev.flags or "truncated_title" in ev.flags
        )
        url_disagreement = int("title_url_mismatch" in ev.flags)
        return (
            quality,
            pollution,
            url_disagreement,
            reliability,
            -float(ev.confidence),
            -len(str(ev.value or "")),
            ev.evidence_id,
        )
    if ev.fact_type == "product.description":
        boundary_excerpt = int("description_hard_boundary" in ev.flags)
        return (
            quality,
            boundary_excerpt,
            reliability,
            directness,
            -float(ev.confidence),
            ev.evidence_id,
        )
    if ev.fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE:
        inferred_from_symbol = int(
            str(ev.metadata.get("derived_by") or "") == "currency_from_price_symbol"
        )
        return (
            quality,
            inferred_from_symbol,
            reliability,
            directness,
            -float(ev.confidence),
            ev.evidence_id,
        )
    if ev.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE:
        derived_penalty = int(bool(ev.metadata.get("derived_by")))
        derived_rank = {
            "brand_from_product_url": 0,
            "brand_from_title_marker": 1,
            "page_identity": 2,
            "brand_from_title_host": 3,
        }.get(str(ev.metadata.get("derived_by") or ""), 1)
        return (
            quality,
            derived_penalty,
            reliability,
            directness,
            derived_rank,
            -float(ev.confidence),
            ev.evidence_id,
        )
    return (
        quality,
        reliability,
        directness,
        -float(ev.confidence),
        ev.evidence_id,
    )
