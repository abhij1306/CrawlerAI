from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from app.core.config.extraction_rules import (
    AVAILABILITY_CANONICAL_ENUM,
    INVALID_AVAILABILITY_EVIDENCE_FLAG,
    normalize_availability_value,
)
from app.core.records.normalizers import normalize_value
from app.core.records.output_safety import public_availability
from app.extraction.collectors._helpers import evidence
from app.extraction.pipeline import _normalize_availability_value
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    RequestContext,
    SourceLocator,
)
from app.extraction.entities import build_entities
from app.extraction.validation import validate

pytestmark = pytest.mark.unit


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-slices-7-9",
        run_id=1,
        requested_url="https://shop.test/products/item",
        final_url="https://shop.test/products/item",
        request_context=RequestContext(context_id="ctx-slices-7-9"),
        artifacts=(),
        acquisition_outcome="success",
    )


def _product(bundle: CaptureBundle):
    return evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="json_pointer", value="/product/url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        subject_id="product-1",
    )


def test_option_inventory_without_sellable_identity_is_not_variant() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "dom",
            "variant.option.size",
            "S M L XL",
            SourceLocator(kind="css_selector", value=".sizes"),
            hint=EntityHint(entity_type="variant"),
            subject_id="variant-options",
            parent_subject_id="product-1",
        ),
    )

    entities = build_entities(bundle, rows)

    assert entities.variants == ()


def test_real_variant_with_sku_remains_variant() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.option.size",
            "S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/size"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].identity_key == "sku:SKU-S"


def test_size_only_variant_identity_merges_with_single_color_size_counterpart() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.id",
            "id-6",
            SourceLocator(kind="json_pointer", value="/skus/0/id"),
            hint=EntityHint(entity_type="variant", variant_id="id-6"),
            subject_id="variant-size-6",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.sku",
            "sku-6",
            SourceLocator(kind="json_pointer", value="/skus/0/sku"),
            hint=EntityHint(entity_type="variant", sku="sku-6"),
            subject_id="variant-size-6",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.option.size",
            "6",
            SourceLocator(kind="json_pointer", value="/skus/0/size"),
            hint=EntityHint(entity_type="variant", variant_id="id-6"),
            subject_id="variant-size-6",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.gtin",
            "00194500874886",
            SourceLocator(kind="json_pointer", value="/availability/0/gtin"),
            hint=EntityHint(entity_type="variant"),
            subject_id="variant-white-6",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.option.color",
            "White/White",
            SourceLocator(kind="json_pointer", value="/availability/0/color"),
            hint=EntityHint(entity_type="variant"),
            subject_id="variant-white-6",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "js_state",
            "variant.option.size",
            "6",
            SourceLocator(kind="json_pointer", value="/availability/0/size"),
            hint=EntityHint(entity_type="variant"),
            subject_id="variant-white-6",
            parent_subject_id="product-1",
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    variant = entities.variants[0]
    assert variant.option_values == {"color": "White/White", "size": "6"}
    assert set(variant.attribute_evidence) >= {
        "variant.id",
        "variant.sku",
        "variant.gtin",
    }


def test_mixed_product_and_variant_offer_ownership_is_rejected() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-S",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-S"),
            subject_id="variant-s",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "offer.price",
            "10.00",
            SourceLocator(kind="json_pointer", value="/offers/0/price"),
            hint=EntityHint(entity_type="offer"),
            group_id="offer-1",
            subject_id="offer-1",
            parent_subject_id="product-1",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "offer.currency",
            "USD",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/offers/0/currency"),
            hint=EntityHint(entity_type="offer"),
            group_id="offer-1",
            subject_id="offer-1",
            parent_subject_id="variant-s",
            parent_scope="variant",
        ),
    )

    entities = build_entities(bundle, rows)
    findings = validate(rows, entities)

    assert entities.offers == ()
    assert any(item.rule_id == "OFFER_RELATION_CONFLICT" for item in findings)


def test_unattached_variant_offer_emits_explicit_join_diagnostics() -> None:
    bundle = _bundle()
    rows = (
        _product(bundle),
        evidence(
            bundle,
            "artifact-1",
            "network",
            "offer.price",
            "10.00",
            SourceLocator(kind="network_json_pointer", value="/variants/0/price"),
            hint=EntityHint(entity_type="offer"),
            group_id="orphan-offer",
            subject_id="orphan-offer",
            parent_subject_id="missing-variant",
            parent_scope="variant",
        ),
    )

    entities = build_entities(bundle, rows)
    finding = next(
        item for item in validate(rows, entities) if item.rule_id == "CHILD_JOIN_FAILED"
    )

    assert finding.evidence_ids == (rows[1].evidence_id,)
    assert finding.metadata["candidate_parent_ids"] == ()
    assert finding.metadata["missing_relation_keys"] == ("entity_hint.sku",)
    assert finding.metadata["conflicting_relation_keys"] == ()
    assert finding.metadata["source_paths"] == ("artifact-1:/variants/0/price",)
    assert finding.metadata["budget_removed_required_key"] is False


def test_availability_is_canonicalized_with_raw_provenance_retained() -> None:
    bundle = _bundle()
    item = evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "offer.availability",
        "https://schema.org/InStock",
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
    )

    assert item.raw_value == "https://schema.org/InStock"
    assert item.value == "in_stock"


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("LimitedAvailability", "limited_stock"),
        ("low_stock", "limited_stock"),
        ("PreOrder", "preorder"),
        ("BackOrder", "backorder"),
        ("Discontinued", "discontinued"),
    ),
)
def test_supported_availability_states_share_canonical_semantics(
    raw: str, expected: str
) -> None:
    bundle = _bundle()
    item = evidence(
        bundle,
        "artifact-1",
        "jsonld",
        "offer.availability",
        raw,
        SourceLocator(kind="json_pointer", value="/offers/availability"),
        hint=EntityHint(entity_type="offer"),
        parent_subject_id="product-1",
    )

    assert item.raw_value == raw
    assert item.value == expected
    assert public_availability(item.value) == expected
    assert public_availability(raw) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("https://schema.org/InStock", "in_stock"),
        ("PreOrder", "preorder"),
        ("BackOrder", "backorder"),
        ("Discontinued", "discontinued"),
        ("SoldOut", "out_of_stock"),
    ),
)
def test_pipeline_availability_normalizes_to_enum_without_flag(
    raw: str, expected: str
) -> None:
    flags: set[str] = set()
    assert _normalize_availability_value(raw, flags) == expected
    assert expected in AVAILABILITY_CANONICAL_ENUM
    assert INVALID_AVAILABILITY_EVIDENCE_FLAG not in flags


@pytest.mark.parametrize(
    "raw",
    ("ships in 3 weeks", "call for availability", "see store", "??"),
)
def test_pipeline_availability_flags_non_enum_values(raw: str) -> None:
    flags: set[str] = set()
    normalized = _normalize_availability_value(raw, flags)
    # Raw text is preserved for the diagnose artifact, but the value is flagged
    # so resolution ranks it below enum-valid candidates and publication drops
    # it — never a silent free-text passthrough into the public record.
    assert normalized not in AVAILABILITY_CANONICAL_ENUM
    assert INVALID_AVAILABILITY_EVIDENCE_FLAG in flags
    assert public_availability(normalized) == ""


def test_availability_normalizers_share_config_authority() -> None:
    assert normalize_availability_value("https://schema.org/PreOrder") == "preorder"
    assert normalize_value("availability", "pre order") == "preorder"
    flags: set[str] = set()
    assert _normalize_availability_value("pre order", flags) == "preorder"
    assert INVALID_AVAILABILITY_EVIDENCE_FLAG not in flags


def test_decimal_availability_flags_normalize_to_stock_states() -> None:
    assert normalize_availability_value(Decimal("1")) == "in_stock"
    assert normalize_availability_value(Fraction(0, 1)) == "out_of_stock"


def test_complex_availability_value_is_not_treated_as_stock_number() -> None:
    assert normalize_availability_value(complex(1, 0)) == "(1+0j)"


def test_duplicate_offers_for_one_variant_do_not_fake_complete_coverage() -> None:
    bundle = _bundle()
    rows = [
        _product(bundle),
        *(
            evidence(
                bundle,
                "artifact-1",
                "jsonld",
                "variant.sku",
                sku,
                SourceLocator(kind="json_pointer", value=f"/variants/{sku}"),
                hint=EntityHint(entity_type="variant", sku=sku),
                subject_id=subject_id,
                parent_subject_id="product-1",
                parent_scope="product",
            )
            for sku, subject_id in (("SKU-S", "variant-s"), ("SKU-M", "variant-m"))
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "offer.availability",
            "out_of_stock",
            SourceLocator(kind="json_pointer", value="/offers/availability"),
            hint=EntityHint(entity_type="offer"),
            group_id="parent-offer",
            parent_subject_id="product-1",
            parent_scope="product",
        ),
        *(
            evidence(
                bundle,
                "artifact-1",
                "jsonld",
                "offer.availability",
                "in_stock",
                SourceLocator(kind="json_pointer", value=f"/offers/{index}"),
                hint=EntityHint(entity_type="offer", sku="SKU-S"),
                group_id=f"variant-offer-{index}",
                parent_subject_id="variant-s",
                parent_scope="variant",
            )
            for index in range(2)
        ),
    ]

    entities = build_entities(bundle, tuple(rows))
    findings = validate(tuple(rows), entities)

    assert len(entities.variants) == 2
    assert any(
        finding.rule_id == "PARENT_VARIANT_AVAILABILITY_CONFLICT"
        for finding in findings
    )
