from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.core.config.extraction_rules import (
    DETAIL_SHELL_FINDING_RULE_ID,
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_TITLE_REJECTION_FLAGS,
)
from app.core.config.variant_policy import CHILD_JOIN_FAILED_RULE_ID
from app.core.config.field_mappings import (
    ECOMMERCE_DETAIL_CRITICAL_CONTRACT_FIELDS,
    ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD,
)
from app.extraction.contracts import Evidence, Finding, PublicRecord
from app.extraction.entities import EntitySet
from app.core.shared.ids import stable_id

FindingScope = Literal[
    "artifact",
    "entity",
    "candidate",
    "selected_entity",
    "selected_public_value",
    "page",
]


def validate(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Finding, ...]:
    relation_conflicts = _validate_offer_relation_conflicts(evidence)
    conflicted_group_ids = {
        str(finding.metadata.get("group_id"))
        for finding in relation_conflicts
        if finding.metadata.get("group_id") is not None
    }
    return (
        *_validate_identity(evidence, entities),
        *_validate_shell_title(evidence, entities),
        *_validate_descriptions(evidence, entities),
        *_validate_variants(entities),
        *_validate_offers(evidence, entities),
        *relation_conflicts,
        *_validate_child_join_failures(
            evidence, entities, skip_group_ids=conflicted_group_ids
        ),
        *_validate_availability_consistency(evidence, entities),
        *_validate_output(entities),
    )


def validate_selected_contract_fields(
    records: tuple[PublicRecord, ...],
    requested_fields: tuple[str, ...],
    evidence: tuple[Evidence, ...] = (),
) -> tuple[Finding, ...]:
    record = records[0] if records else None
    availability_exposed = _availability_exposed(record, evidence)
    # Price and currency are required; availability is conditional on exposure.
    availability_fields = (
        (ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD,) if availability_exposed else ()
    )
    contract_fields = tuple(
        dict.fromkeys(
            (
                *ECOMMERCE_DETAIL_CRITICAL_CONTRACT_FIELDS,
                *availability_fields,
                *requested_fields,
            )
        )
    )
    missing_fields: list[str] = []
    findings: list[Finding] = []
    for field in contract_fields:
        public_field = "image_url" if field == "image" else field
        present = bool(
            record is not None
            and record.get(public_field) not in (None, "", [], {}, ())
        )
        if present:
            continue
        missing_fields.append(field)
        findings.append(
            _finding(
                "MISSING_CONTRACT_FIELD",
                (),
                (),
                f"No admissible evidence for contract field {field!r}.",
                False,
                metadata={"field": field},
            )
        )
    present_count = len(contract_fields) - len(missing_fields)
    score = present_count / len(contract_fields) if contract_fields else 0.0
    if record is None or record.get("title") in (None, "", [], {}, ()):
        rejected_title_ids = tuple(
            row.evidence_id
            for row in evidence
            if row.fact_type == "product.title"
            and (
                row.collector_id == "url"
                or bool(set(row.flags).intersection(DETAIL_TITLE_REJECTION_FLAGS))
            )
        )
        findings.append(
            _finding(
                "MISSING_OR_GENERIC_TITLE",
                (),
                rejected_title_ids,
                "No admissible product-specific title was selected.",
                False,
                metadata={"field": "title"},
            )
        )
    findings.append(
        _finding(
            "RECORD_COMPLETENESS",
            (),
            (),
            f"Selected public record completeness is {score:.3f}.",
            False,
            metadata={
                "score": score,
                "present_count": present_count,
                "required_count": len(contract_fields),
                "missing_fields": tuple(missing_fields),
                "contract_fields": contract_fields,
            },
        )
    )
    return tuple(findings)


def _availability_exposed(
    record: PublicRecord | None, evidence: tuple[Evidence, ...]
) -> bool:
    if record is not None and record.get("availability") not in (
        None,
        "",
        [],
        {},
        (),
    ):
        return True
    return any(
        row.fact_type == "offer.availability"
        and "invalid_availability" not in row.flags
        for row in evidence
    )


def _validate_identity(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> tuple[Finding, ...]:
    if not entities.products:
        ids = tuple(
            sorted(
                ev.evidence_id for ev in evidence if ev.fact_type.startswith("product.")
            )
        )
        return (
            _finding(
                "MISSING_PRODUCT_IDENTITY", (), ids, "No primary product entity.", True
            ),
        )
    if len(entities.products) > 1:
        return (
            _finding(
                "PRIMARY_PRODUCT_AMBIGUOUS",
                tuple(p.entity_id for p in entities.products),
                (),
                "Primary product ambiguous.",
                True,
            ),
        )
    return ()


def _validate_shell_title(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> tuple[Finding, ...]:
    if len(entities.products) != 1:
        return ()
    product = entities.products[0]
    by_id = {row.evidence_id: row for row in evidence}
    titles = tuple(
        by_id[eid]
        for eid in product.attribute_evidence.get("product.title", ())
        if eid in by_id
    )
    shell_ids = tuple(
        row.evidence_id for row in titles if DETAIL_SHELL_TITLE_FLAG in row.flags
    )
    has_admissible_title = any(
        row.collector_id != "url"
        and not set(row.flags).intersection(DETAIL_TITLE_REJECTION_FLAGS)
        for row in titles
    )
    if not shell_ids or has_admissible_title:
        return ()
    return (
        _finding(
            DETAIL_SHELL_FINDING_RULE_ID,
            (product.entity_id,),
            shell_ids,
            "Selected product title evidence is an HTTP or transient UI shell.",
            True,
        ),
    )


def _validate_descriptions(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> tuple[Finding, ...]:
    if len(entities.products) != 1:
        return ()
    product = entities.products[0]
    by_id = {row.evidence_id: row for row in evidence}
    descriptions = tuple(
        by_id[eid]
        for eid in product.attribute_evidence.get("product.description", ())
        if eid in by_id
    )
    findings: list[Finding] = []
    boundary_ids = tuple(
        row.evidence_id
        for row in descriptions
        if "description_hard_boundary" in row.flags
    )
    if boundary_ids:
        findings.append(
            _finding(
                "DESCRIPTION_HARD_BOUNDARY",
                (product.entity_id,),
                boundary_ids,
                "Description length matches a known extractor/source excerpt boundary.",
                False,
            )
        )
    incomplete_ids = tuple(
        row.evidence_id
        for row in descriptions
        if "description_incomplete_ending" in row.flags
    )
    if incomplete_ids:
        findings.append(
            _finding(
                "DESCRIPTION_INCOMPLETE_ENDING",
                (product.entity_id,),
                incomplete_ids,
                "Description ends with an incomplete connector or preposition.",
                False,
            )
        )
    has_clean_description = any(
        "description_promotional_copy" not in row.flags for row in descriptions
    )
    promotional_ids: tuple[str, ...] = ()
    if not has_clean_description:
        promotional_ids = tuple(
            row.evidence_id
            for row in descriptions
            if "description_promotional_copy" in row.flags
        )
    if promotional_ids:
        findings.append(
            _finding(
                "DESCRIPTION_PROMOTIONAL_COPY",
                (product.entity_id,),
                promotional_ids,
                "Description evidence is promotional, shipping, search, or directory copy.",
                False,
            )
        )
    return tuple(findings)


def _validate_variants(entities: EntitySet) -> tuple[Finding, ...]:
    out: list[Finding] = list(_validate_expected_variant_axes(entities))
    keys = [variant.identity_key for variant in entities.variants]
    if any(count > 1 for count in Counter(keys).values()):
        out.append(
            _finding(
                "DUPLICATE_VARIANT_IDENTITY",
                tuple(v.entity_id for v in entities.variants),
                (),
                "Duplicate variant identity.",
                True,
            )
        )
    for variant in entities.variants:
        if _publishable_variant(variant, entities):
            continue
        out.append(
            _finding(
                "INCOMPLETE_VARIANT_EVIDENCE",
                (variant.entity_id,),
                variant.identity_evidence_ids,
                "Variant evidence has identity but no option or commercial fact.",
                False,
            )
        )
    out.extend(_validate_variant_availability(entities))
    return tuple(out)


def _validate_expected_variant_axes(entities: EntitySet) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    variants_by_product = {
        product.entity_id: tuple(
            variant
            for variant in entities.variants
            if variant.product_entity_id == product.entity_id
        )
        for product in entities.products
    }
    for catalog in entities.option_catalogs:
        variants = variants_by_product.get(catalog.product_entity_id, ())
        for axis in catalog.axes:
            expected_values = tuple(
                value.value for value in axis.values if str(value.value).strip()
            )
            if len(set(expected_values)) < 2:
                continue
            missing = tuple(
                variant.entity_id
                for variant in variants
                if not str(variant.option_values.get(axis.axis) or "").strip()
            )
            if variants and not missing:
                continue
            evidence_ids = tuple(
                evidence_id
                for value in axis.values
                for evidence_id in value.evidence_ids
            )
            findings.append(
                _finding(
                    "EXPECTED_VARIANT_AXIS_MISSING",
                    missing or (catalog.product_entity_id,),
                    evidence_ids,
                    f"Explicit variant axis {axis.axis!r} is not complete in public variants.",
                    False,
                    metadata={
                        "axis": axis.axis,
                        "expected_values": expected_values,
                        "variant_count": len(variants),
                        "missing_variant_count": len(missing) if variants else 0,
                    },
                )
            )
    return tuple(findings)


def _validate_variant_availability(entities: EntitySet) -> tuple[Finding, ...]:
    parent_has_availability = any(
        offer.variant_entity_id is None and _offer_has_availability_signal(offer)
        for offer in entities.offers
    )
    findings: list[Finding] = []
    for variant in entities.variants:
        offers = tuple(
            offer
            for offer in entities.offers
            if offer.variant_entity_id == variant.entity_id
        )
        sellable = any(
            offer.fact_evidence.get("offer.price")
            and offer.fact_evidence.get("offer.currency")
            for offer in offers
        )
        has_availability = any(
            _offer_has_availability_signal(offer) for offer in offers
        )
        if not sellable or has_availability or parent_has_availability:
            continue
        findings.append(
            _finding(
                "VARIANT_AVAILABILITY_MISSING",
                (variant.entity_id,),
                tuple(
                    evidence_id
                    for offer in offers
                    for fact in ("offer.price", "offer.currency")
                    for evidence_id in offer.fact_evidence.get(fact, ())
                ),
                "Sellable variant has no availability evidence.",
                False,
                metadata={"variant_identity": variant.identity_key},
            )
        )
    return tuple(findings)


def _offer_has_availability_signal(offer) -> bool:
    return bool(
        offer.fact_evidence.get("offer.availability")
        or offer.fact_evidence.get("offer.stock_quantity")
    )


def _publishable_variant(variant, entities: EntitySet) -> bool:
    if variant.option_values:
        return True
    commercial_facts = {
        "offer.price",
        "offer.currency",
        "offer.availability",
        "offer.stock_quantity",
    }
    return any(
        offer.variant_entity_id == variant.entity_id
        and bool(commercial_facts & set(offer.fact_evidence))
        for offer in entities.offers
    )


def _validate_offers(
    evidence: tuple[Evidence, ...], entities: EntitySet
) -> tuple[Finding, ...]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    out: list[Finding] = []
    # Parent offers combine at publication scope; only unresolved gaps are primary.
    parent_has_price = any(
        offer.variant_entity_id is None and bool(offer.fact_evidence.get("offer.price"))
        for offer in entities.offers
    )
    parent_has_currency = any(
        offer.variant_entity_id is None
        and bool(offer.fact_evidence.get("offer.currency"))
        for offer in entities.offers
    )
    price_without_currency: dict[bool, list[tuple[str, tuple[str, ...]]]] = {
        True: [],
        False: [],
    }
    currency_without_price: dict[bool, list[tuple[str, tuple[str, ...]]]] = {
        True: [],
        False: [],
    }
    for offer in entities.offers:
        is_product_level = offer.variant_entity_id is None
        has_price = bool(offer.fact_evidence.get("offer.price"))
        has_currency = bool(offer.fact_evidence.get("offer.currency"))
        if has_price and not has_currency:
            is_primary = is_product_level and not parent_has_currency
            price_without_currency[is_primary].append(
                (offer.entity_id, offer.fact_evidence.get("offer.price", ()))
            )
        if has_currency and not has_price:
            is_primary = is_product_level and not parent_has_price
            currency_without_price[is_primary].append(
                (offer.entity_id, offer.fact_evidence.get("offer.currency", ()))
            )
        current = _decimal(offer.fact_evidence.get("offer.price", ()), by_id)
        original = _decimal(offer.fact_evidence.get("offer.original_price", ()), by_id)
        if current is not None and current <= 0:
            out.append(
                _finding(
                    "NON_POSITIVE_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.price", ()),
                    "Offer price must be positive.",
                    False,
                )
            )
        if current is not None and original is not None and original < current:
            out.append(
                _finding(
                    "INVALID_ORIGINAL_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.original_price", ()),
                    "Original price below current price.",
                    True,
                )
            )
    for rule, buckets, message in (
        (
            "PRICE_WITHOUT_CURRENCY",
            price_without_currency,
            "Offer price lacks currency.",
        ),
        (
            "CURRENCY_WITHOUT_PRICE",
            currency_without_price,
            "Offer currency lacks price.",
        ),
    ):
        out.extend(
            _grouped_offer_completeness_findings(
                rule=rule, rows=buckets[True], message=message, scope="selected_entity"
            )
        )
        out.extend(
            _grouped_offer_completeness_findings(
                rule=rule, rows=buckets[False], message=message, scope="candidate"
            )
        )
    return tuple(out)


def _grouped_offer_completeness_findings(
    *,
    rule: str,
    rows: list[tuple[str, tuple[str, ...]]],
    message: str,
    scope: FindingScope,
) -> tuple[Finding, ...]:
    if not rows:
        return ()
    if len(rows) == 1:
        entity_id, evidence_ids = rows[0]
        return (
            _finding(rule, (entity_id,), evidence_ids, message, False, scope=scope),
        )
    evidence_ids = tuple(
        dict.fromkeys(evidence_id for _entity_id, ids in rows for evidence_id in ids)
    )
    examples = tuple(entity_id for entity_id, _ids in rows[:5])
    return (
        _finding(
            rule,
            (),
            evidence_ids[:20],
            f"{len(rows)} candidate offers have incomplete price/currency pairs.",
            False,
            metadata={
                "candidate_offer_count": len(rows),
                "example_offer_entity_ids": examples,
            },
            scope=scope,
        ),
    )


def _validate_offer_relation_conflicts(
    evidence: tuple[Evidence, ...],
) -> tuple[Finding, ...]:
    groups: dict[str, list[Evidence]] = {}
    for row in evidence:
        if not row.fact_type.startswith("offer."):
            continue
        group_id = row.group_id or f"ungrouped:{row.evidence_id}"
        groups.setdefault(group_id, []).append(row)

    findings: list[Finding] = []
    for group_id, rows in sorted(groups.items()):
        relations = {row.relation_type for row in rows if row.relation_type}
        parent_subject_ids = {
            row.parent_subject_id for row in rows if row.parent_subject_id
        }
        mixed_implicit_ownership = (
            "variant_offer" in relations
            and len(parent_subject_ids) > 1
            and any(row.relation_type is None for row in rows)
        )
        if len(relations) <= 1 and not mixed_implicit_ownership:
            continue
        findings.append(
            _finding(
                "OFFER_RELATION_CONFLICT",
                (),
                tuple(sorted(row.evidence_id for row in rows)),
                "Offer evidence declares conflicting product and variant ownership.",
                True,
                metadata={
                    "group_id": group_id,
                    "relation_types": tuple(sorted(relations)),
                },
            )
        )
    return tuple(findings)


def _validate_child_join_failures(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    *,
    skip_group_ids: frozenset[str] | set[str] = frozenset(),
) -> tuple[Finding, ...]:
    linked_group_ids = {
        offer.group_id
        for offer in entities.offers
        if offer.variant_entity_id is not None
    }
    variant_subjects = {
        subject_id: variant.entity_id
        for variant in entities.variants
        for subject_id in variant.source_subject_ids
    }
    variants_by_sku = {
        variant.identity_key.split(":", 1)[1]: variant.entity_id
        for variant in entities.variants
        if variant.identity_key.startswith("sku:")
    }
    groups: dict[str, list[Evidence]] = {}
    for row in evidence:
        if row.fact_type.startswith("offer."):
            groups.setdefault(
                row.group_id or f"ungrouped:{row.evidence_id}", []
            ).append(row)

    findings: list[Finding] = []
    for group_id, rows in sorted(groups.items()):
        if group_id in linked_group_ids or group_id in skip_group_ids:
            continue
        if not any(row.relation_type == "variant_offer" for row in rows):
            continue
        relations = {row.relation_type for row in rows if row.relation_type}
        candidate_parent_ids = tuple(
            sorted(
                {
                    candidate_id
                    for row in rows
                    for candidate_id in (
                        variant_subjects.get(row.parent_subject_id or ""),
                        variants_by_sku.get(
                            str(row.entity_hint.sku)
                            if row.entity_hint and row.entity_hint.sku
                            else ""
                        ),
                    )
                    if candidate_id
                }
            )
        )
        missing_keys = tuple(
            key
            for key, present in (
                ("parent_subject_id", any(row.parent_subject_id for row in rows)),
                (
                    "entity_hint.sku",
                    any(row.entity_hint and row.entity_hint.sku for row in rows),
                ),
            )
            if not present
        )
        conflicting_keys = tuple(
            key
            for key, conflicted in (
                ("relation_type", len(relations) > 1),
                ("candidate_parent_id", len(candidate_parent_ids) > 1),
            )
            if conflicted
        )
        findings.append(
            _finding(
                CHILD_JOIN_FAILED_RULE_ID,
                candidate_parent_ids,
                tuple(sorted(row.evidence_id for row in rows)),
                "Captured child evidence could not be attached to one parent entity.",
                False,
                metadata={
                    "group_id": group_id,
                    "candidate_parent_ids": candidate_parent_ids,
                    "missing_relation_keys": missing_keys,
                    "conflicting_relation_keys": conflicting_keys,
                    "source_paths": tuple(
                        dict.fromkeys(
                            f"{row.artifact_id}:{row.locator.value}" for row in rows
                        )
                    ),
                    "budget_removed_required_key": False,
                    "child_fact_types": tuple(sorted({row.fact_type for row in rows})),
                },
            )
        )
    return tuple(findings)


def _validate_availability_consistency(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
) -> tuple[Finding, ...]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    parent_offers = [
        offer for offer in entities.offers if offer.variant_entity_id is None
    ]
    variant_offers = [
        offer for offer in entities.offers if offer.variant_entity_id is not None
    ]
    if (
        not entities.variants
        or not parent_offers
        or len(variant_offers) < len(entities.variants)
    ):
        return ()
    child_ids = [
        offer.fact_evidence.get("offer.availability", ()) for offer in variant_offers
    ]
    if any(not ids for ids in child_ids):
        return ()
    child_values = [str(by_id[ids[0]].value) for ids in child_ids if ids[0] in by_id]
    if len(child_values) != len(variant_offers):
        return ()
    aggregate = "in_stock" if "in_stock" in child_values else "out_of_stock"
    parent_ids = parent_offers[0].fact_evidence.get("offer.availability", ())
    if not parent_ids or parent_ids[0] not in by_id:
        return ()
    parent_value = str(by_id[parent_ids[0]].value)
    if parent_value == aggregate:
        return ()
    # Complete child matrices supersede selected-configuration parent availability.
    covered_variant_ids = {
        offer.variant_entity_id
        for offer in variant_offers
        if offer.variant_entity_id is not None
    }
    if covered_variant_ids == {variant.entity_id for variant in entities.variants}:
        return ()
    evidence_ids = tuple(parent_ids) + tuple(eid for ids in child_ids for eid in ids)
    return (
        _finding(
            "PARENT_VARIANT_AVAILABILITY_CONFLICT",
            (parent_offers[0].entity_id,),
            evidence_ids,
            "Parent availability conflicts with captured variant availability.",
            False,
        ),
    )


def _validate_output(entities: EntitySet) -> tuple[Finding, ...]:
    if not entities.products:
        return ()
    product = entities.products[0]
    has_title = bool(product.attribute_evidence.get("product.title"))
    has_url = bool(product.attribute_evidence.get("product.url"))
    if not has_title or not has_url:
        ids = tuple(
            sorted(
                set(
                    product.attribute_evidence.get("product.title", ())
                    + product.attribute_evidence.get("product.url", ())
                )
            )
        )
        return (
            _finding(
                "INSUFFICIENT_PRODUCT_KNOWLEDGE",
                (product.entity_id,),
                ids,
                "Product lacks title or URL.",
                False,
            ),
        )
    return ()


def _decimal(ids: tuple[str, ...] | None, by_id: dict[str, Evidence]) -> Decimal | None:
    if not ids:
        return None
    # A malformed leading value must not mask later valid evidence.
    for evidence_id in ids:
        try:
            return Decimal(str(by_id[evidence_id].value))
        except (KeyError, InvalidOperation, ValueError):
            continue
    return None


def _finding(
    rule: str,
    entity_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    message: str,
    blocking: bool,
    metadata: dict[str, object] | None = None,
    scope: FindingScope | None = None,
) -> Finding:
    return Finding(
        finding_id=stable_id("finding", rule, entity_ids, evidence_ids),
        rule_id=rule,
        severity="high" if blocking else "medium",
        scope=scope or ("selected_entity" if entity_ids else "page"),
        entity_ids=entity_ids,
        evidence_ids=evidence_ids,
        message=message,
        blocking=blocking,
        metadata=metadata or {},
    )
