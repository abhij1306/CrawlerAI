from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from app.core.config.extraction_rules import (
    DETAIL_SHELL_FINDING_RULE_ID,
    DETAIL_SHELL_TITLE_FLAG,
    DETAIL_TITLE_REJECTION_FLAGS,
)
from app.core.config.field_mappings import (
    ECOMMERCE_DETAIL_DEFAULT_CONTRACT_FIELDS,
    ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD,
    ECOMMERCE_DETAIL_SELLABLE_OFFER_FIELDS,
)
from app.extraction.contracts import Evidence, Finding, PublicRecord
from app.extraction.entities import EntitySet
from app.extraction.ids import stable_id


def validate(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
    requested_fields: tuple[str, ...] = (),
) -> tuple[Finding, ...]:
    return (
        *_validate_identity(evidence, entities),
        *_validate_shell_title(evidence, entities),
        *_validate_descriptions(evidence, entities),
        *_validate_variants(entities),
        *_validate_offers(evidence, entities),
        *_validate_availability_consistency(evidence, entities),
        *_validate_output(entities),
    )


def validate_selected_contract_fields(
    records: tuple[PublicRecord, ...],
    requested_fields: tuple[str, ...],
    evidence: tuple[Evidence, ...] = (),
) -> tuple[Finding, ...]:
    record = records[0] if records else None
    sellable_offer_exposed = _sellable_offer_exposed(record, evidence)
    availability_exposed = _availability_exposed(record, evidence)
    conditional_fields = (
        ECOMMERCE_DETAIL_SELLABLE_OFFER_FIELDS if sellable_offer_exposed else ()
    )
    availability_fields = (
        (ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD,)
        if availability_exposed
        else ()
    )
    contract_fields = tuple(
        dict.fromkeys(
            (
                *ECOMMERCE_DETAIL_DEFAULT_CONTRACT_FIELDS,
                *conditional_fields,
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


def _sellable_offer_exposed(
    record: PublicRecord | None, evidence: tuple[Evidence, ...]
) -> bool:
    if record is not None and any(
        record.get(field) not in (None, "", [], {}, ())
        for field in ("price", "currency", "original_price", "variants")
    ):
        return True
    return any(
        row.fact_type in {"offer.price", "offer.currency", "offer.original_price"}
        and "invalid_decimal" not in row.flags
        and "invalid_currency" not in row.flags
        for row in evidence
    )


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
        offer.variant_entity_id is None
        and bool(offer.fact_evidence.get("offer.availability"))
        for offer in entities.offers
    )
    findings: list[Finding] = []
    for variant in entities.variants:
        offers = tuple(
            offer for offer in entities.offers if offer.variant_entity_id == variant.entity_id
        )
        sellable = any(
            offer.fact_evidence.get("offer.price")
            and offer.fact_evidence.get("offer.currency")
            for offer in offers
        )
        has_availability = any(
            offer.fact_evidence.get("offer.availability") for offer in offers
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
    for offer in entities.offers:
        has_price = bool(offer.fact_evidence.get("offer.price"))
        has_currency = bool(offer.fact_evidence.get("offer.currency"))
        if has_price and not has_currency:
            out.append(
                _finding(
                    "PRICE_WITHOUT_CURRENCY",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.price", ()),
                    "Offer price lacks currency.",
                    False,
                )
            )
        if has_currency and not has_price:
            out.append(
                _finding(
                    "CURRENCY_WITHOUT_PRICE",
                    (offer.entity_id,),
                    offer.fact_evidence.get("offer.currency", ()),
                    "Offer currency lacks price.",
                    False,
                )
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
    return tuple(out)


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
    if (
        not parent_ids
        or parent_ids[0] not in by_id
        or str(by_id[parent_ids[0]].value) == aggregate
    ):
        return ()
    evidence_ids = tuple(parent_ids) + tuple(eid for ids in child_ids for eid in ids)
    return (
        _finding(
            "PARENT_VARIANT_AVAILABILITY_CONFLICT",
            (parent_offers[0].entity_id,),
            evidence_ids,
            "Parent availability conflicts with the complete variant matrix.",
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
    try:
        return Decimal(str(by_id[ids[0]].value))
    except (KeyError, InvalidOperation, ValueError):
        return None


def _finding(
    rule: str,
    entity_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    message: str,
    blocking: bool,
    metadata: dict[str, object] | None = None,
) -> Finding:
    return Finding(
        finding_id=stable_id("finding", rule, entity_ids, evidence_ids),
        rule_id=rule,
        severity="high" if blocking else "medium",
        scope="selected_entity" if entity_ids else "page",
        entity_ids=entity_ids,
        evidence_ids=evidence_ids,
        message=message,
        blocking=blocking,
        metadata=metadata or {},
    )
