"""Phase 1.1 — resolution ranking spine (precision / the phantom-DOM bug).

``_rank`` orders candidates on a single shared spine
``(value_quality, reliability, directness, …)`` so that *source reliability beats
directness*: an embedded JSON-LD offer outranks a phantom ``[data-price]`` DOM
scrape, and a shape-valid value outranks a shape-invalid one even when the
invalid value carried no rejection flag. Field-specific quality terms
(title pollution, brand derivation) ride on top of that spine and are preserved.
"""

from __future__ import annotations

import pytest

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_TITLE_SOURCE_ROLE_DOCUMENT,
    DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY,
    DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT,
    DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING,
)
from app.extraction.contracts import Decision, EntityHint, Evidence, SourceLocator
from app.extraction.entities import EntitySet, OfferEntity, VariantEntity
from app.extraction.resolution import (
    _preferred_parent_offer_id,
    _rank,
    _resolve_offer,
    _resolve_scalar,
)

pytestmark = pytest.mark.unit


def _evidence(
    evidence_id: str,
    *,
    fact_type: str,
    value: object,
    collector_id: str,
    directness: str = "direct",
    confidence: float = 0.9,
    flags: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
    group_id: str | None = None,
    subject_id: str = "subject-1",
    parent_subject_id: str | None = None,
    url: str | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle-1",
        artifact_id="artifact-1",
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=f"/{evidence_id}"),
        directness=directness,  # type: ignore[arg-type]
        confidence=confidence,
        flags=flags,
        metadata=metadata or {},
        group_id=group_id,
        subject_id=subject_id,
        parent_subject_id=parent_subject_id,
        relation_type="product_offer" if parent_subject_id else None,
        entity_hint=EntityHint(entity_type="offer", url=url) if url else None,
    )


def _winner(*evidence: Evidence) -> str:
    by_id = {ev.evidence_id: ev for ev in evidence}
    decision = _resolve_scalar(
        "entity-1",
        evidence[0].fact_type,
        tuple(by_id),
        by_id,
        (),
    )
    assert decision.status == "resolved"
    return decision.accepted_evidence_ids[0]


def test_jsonld_offer_outranks_phantom_dom_price() -> None:
    # The bug: a `direct` DOM [data-price] used to beat an `embedded` JSON-LD
    # offer because directness preceded reliability. Reliability now wins.
    jsonld = _evidence(
        "ev-jsonld",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="19.99",
        collector_id="jsonld",
        directness="embedded",
    )
    phantom_dom = _evidence(
        "ev-dom",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="9.99",
        collector_id="dom",
        directness="direct",
    )
    assert _rank(jsonld) < _rank(phantom_dom)
    assert _winner(jsonld, phantom_dom) == "ev-jsonld"


def test_checksum_valid_gtin_outranks_invalid_declared_gtin() -> None:
    invalid_jsonld = _evidence(
        "ev-invalid-gtin",
        fact_type=field_mappings.PRODUCT_GTIN_FACT_TYPE,
        value="4006381333932",
        collector_id="jsonld",
        directness="embedded",
    )
    valid_state = _evidence(
        "ev-valid-gtin",
        fact_type=field_mappings.PRODUCT_GTIN_FACT_TYPE,
        value="4006381333931",
        collector_id="js_state",
        directness="embedded",
    )

    assert _winner(invalid_jsonld, valid_state) == "ev-valid-gtin"


def test_offer_price_currency_atomicity_rejects_incompatible_lineage() -> None:
    price = _evidence(
        "ev-price",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="10",
        collector_id="jsonld",
        directness="embedded",
        group_id="offer:one",
        subject_id="offer:one",
        parent_subject_id="product:1",
    )
    currency = _evidence(
        "ev-currency",
        fact_type=field_mappings.OFFER_CURRENCY_FACT_TYPE,
        value="USD",
        collector_id="jsonld",
        directness="embedded",
        group_id="offer:two",
        subject_id="offer:two",
        parent_subject_id="product:2",
    )
    offer = OfferEntity(
        entity_id="offer:1",
        product_entity_id="product:entity",
        variant_entity_id=None,
        group_id="merged-test-offer",
        request_context_id="ctx:1",
        fact_evidence={
            field_mappings.OFFER_PRICE_FACT_TYPE: (price.evidence_id,),
            field_mappings.OFFER_CURRENCY_FACT_TYPE: (currency.evidence_id,),
        },
    )

    decisions = _resolve_offer(
        offer,
        {price.evidence_id: price, currency.evidence_id: currency},
        (),
    )

    assert {row.fact_type: row.status for row in decisions} == {
        field_mappings.OFFER_CURRENCY_FACT_TYPE: "unresolved",
        field_mappings.OFFER_PRICE_FACT_TYPE: "unresolved",
    }
    assert {
        rejected.reason for decision in decisions for rejected in decision.rejected
    } == {"offer_atomic_group_incompatible"}


def test_target_url_offer_outranks_unidentified_sibling_offer() -> None:
    target_bound = _evidence(
        "target-bound",
        fact_type="offer.price_max",
        value="219.95",
        collector_id="jsonld",
        group_id="target",
        url="https://shop.test/products/kettle",
    )
    target_currency = _evidence(
        "target-currency",
        fact_type="offer.currency",
        value="USD",
        collector_id="jsonld",
        group_id="target",
        url="https://shop.test/products/kettle",
    )
    sibling_price = _evidence(
        "sibling-price",
        fact_type="offer.price",
        value="179.95",
        collector_id="jsonld",
        group_id="sibling",
    )
    sibling_currency = _evidence(
        "sibling-currency",
        fact_type="offer.currency",
        value="USD",
        collector_id="jsonld",
        group_id="sibling",
    )
    page_url = _evidence(
        "page-url",
        fact_type="product.url",
        value="https://shop.test/products/kettle",
        collector_id="url",
    )
    target = OfferEntity(
        entity_id="offer-target",
        product_entity_id="product",
        variant_entity_id=None,
        group_id="target",
        request_context_id="ctx",
        target_rank=0,
        fact_evidence={
            "offer.price_max": (target_bound.evidence_id,),
            "offer.currency": (target_currency.evidence_id,),
        },
    )
    sibling = OfferEntity(
        entity_id="offer-sibling",
        product_entity_id="product",
        variant_entity_id=None,
        group_id="sibling",
        request_context_id="ctx",
        target_rank=2,
        fact_evidence={
            "offer.price": (sibling_price.evidence_id,),
            "offer.currency": (sibling_currency.evidence_id,),
        },
    )
    by_id = {
        row.evidence_id: row
        for row in (
            target_bound,
            target_currency,
            sibling_price,
            sibling_currency,
            page_url,
        )
    }
    decisions = [
        Decision(
            decision_id=f"decision-{row.evidence_id}",
            entity_id=entity_id,
            fact_type=row.fact_type,
            accepted_evidence_ids=(row.evidence_id,),
            rejected=(),
            finding_ids=(),
            rule_id="test",
            status="resolved",
        )
        for entity_id, row in (
            (target.entity_id, target_bound),
            (target.entity_id, target_currency),
            (sibling.entity_id, sibling_price),
            (sibling.entity_id, sibling_currency),
        )
    ]
    selected_variant = VariantEntity(
        entity_id="variant-selected",
        product_entity_id="product",
        identity_key="url:target",
        identity_evidence_ids=(),
        option_values={"size": "Large"},
        attribute_evidence={},
        offer_ids=(),
        asset_ids=(),
        selected=True,
    )

    assert (
        _preferred_parent_offer_id(
            EntitySet(variants=(selected_variant,), offers=(sibling, target)),
            decisions,
            by_id,
        )
        == target.entity_id
    )


def test_enum_invalid_availability_loses_to_enum_valid() -> None:
    # Both pass flag-based admissibility (neither is flagged invalid_availability);
    # the shape-only value_quality term breaks the tie toward the canonical enum.
    valid = _evidence(
        "ev-valid",
        fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        value="in_stock",
        collector_id="dom",
    )
    off_enum = _evidence(
        "ev-off-enum",
        fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
        value="on_sale",
        collector_id="jsonld",
        directness="embedded",
    )
    # Even though off_enum comes from a more reliable collector, its non-enum
    # shape ranks it below the canonical value.
    assert _rank(valid) < _rank(off_enum)
    assert _winner(valid, off_enum) == "ev-valid"


def test_malformed_price_loses_to_well_formed_price() -> None:
    well_formed = _evidence(
        "ev-good",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="19.99",
        collector_id="dom",
    )
    malformed = _evidence(
        "ev-bad",
        fact_type=field_mappings.OFFER_PRICE_FACT_TYPE,
        value="call for price",
        collector_id="jsonld",
        directness="embedded",
    )
    assert _rank(well_formed) < _rank(malformed)


def test_title_pollution_ranking_preserved() -> None:
    clean = _evidence(
        "ev-clean",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe",
        collector_id="dom",
    )
    polluted = _evidence(
        "ev-polluted",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe | Buy Now | BrandStore",
        collector_id="jsonld",
        directness="embedded",
        flags=("seo_title_pollution",),
    )
    assert _rank(clean) < _rank(polluted)


def test_title_semantic_source_role_precedes_url_overlap() -> None:
    structured = _evidence(
        "ev-structured",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe",
        collector_id="jsonld",
        metadata={
            DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY: (
                DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT
            ),
            "title_overlap": 1,
            "title_precision": 0.33,
        },
    )
    document = _evidence(
        "ev-document",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Blue Trail Running Shoe TR-100",
        collector_id="dom",
        metadata={
            DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY: DETAIL_TITLE_SOURCE_ROLE_DOCUMENT,
            "title_overlap": 5,
            "title_precision": 1.0,
        },
    )

    assert _winner(structured, document) == structured.evidence_id


def test_visible_product_heading_precedes_document_title() -> None:
    heading = _evidence(
        "ev-heading",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe",
        collector_id="dom",
        metadata={
            DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY: (
                DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING
            )
        },
    )
    document = _evidence(
        "ev-document",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Trail Running Shoe - Blue | Example Store",
        collector_id="dom",
        metadata={
            DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY: DETAIL_TITLE_SOURCE_ROLE_DOCUMENT
        },
    )

    assert _winner(heading, document) == heading.evidence_id


def test_clean_extracted_title_outranks_url_derived_slug_on_partial_overlap() -> None:
    extracted = _evidence(
        "ev-extracted",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="Arizona Birko-Flor",
        collector_id="jsonld",
        flags=("title_url_mismatch",),
        metadata={"title_overlap": 1, "title_precision": 0.33},
    )
    slug = _evidence(
        "ev-slug",
        fact_type=field_mappings.PRODUCT_TITLE_FACT_TYPE,
        value="arizona core birkoflor 0 eva u 1",
        collector_id="url",
        flags=("title_url_match", "url_derived_title"),
        metadata={"title_overlap": 4, "title_precision": 1.0},
    )

    assert _rank(extracted) < _rank(slug)


def test_brand_derivation_ranking_preserved() -> None:
    direct = _evidence(
        "ev-direct",
        fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
        value="Acme",
        collector_id="jsonld",
        directness="embedded",
    )
    derived = _evidence(
        "ev-derived",
        fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
        value="Acme",
        collector_id="dom",
        metadata={"derived_by": "brand_from_title_host"},
    )
    assert _rank(direct) < _rank(derived)
