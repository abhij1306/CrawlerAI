from __future__ import annotations

import pytest

from app.services.extract.detail.assembly.dom_section_targets import (
    record_has_rich_existing_variants,
)
from app.services.extract.detail.resolution import resolve_detail_entities
from app.services.extract.detail.validation import validate_variant_offers
from app.services.extract.variant_normalization import normalize_variant_record


@pytest.mark.regression
def test_size_only_variants_are_not_rich_existing_variants() -> None:
    record = {
        "variants": [
            {"size": "8"},
            {"size": "9"},
            {"size": "10"},
        ]
    }

    assert record_has_rich_existing_variants(record) is False


@pytest.mark.regression
def test_size_only_sellable_variants_emit_offer_completeness_findings() -> None:
    record = {
        "title": "Sneaker",
        "price": "120.00",
        "currency": "USD",
        "variants": [
            {"size": "8"},
            {"size": "9", "availability": "in_stock"},
        ],
    }

    findings = validate_variant_offers(record)

    assert [finding["rule_id"] for finding in findings] == [
        "INCOMPLETE_SELLABLE_VARIANT_OFFER",
        "INCOMPLETE_SELLABLE_VARIANT_OFFER",
    ]
    assert findings[0]["entity_ref"] == "variant:0"
    assert findings[0]["severity"] == "high"


@pytest.mark.regression
def test_explicitly_unavailable_variant_does_not_need_price() -> None:
    record = {
        "variants": [
            {"size": "8", "availability": "out_of_stock"},
            {"size": "9", "availability": "sold_out"},
        ],
    }

    assert validate_variant_offers(record) == []


@pytest.mark.regression
def test_public_variants_keep_inherited_parent_offer_explicitly() -> None:
    record = {
        "price": "100.00",
        "currency": "USD",
        "availability": "in_stock",
        "variants": [
            {"sku": "TREE-8", "size": "8"},
            {"sku": "TREE-9", "size": "9"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {
            "sku": "TREE-8",
            "size": "8",
            "price": "100.00",
            "currency": "USD",
        },
        {
            "sku": "TREE-9",
            "size": "9",
            "price": "100.00",
            "currency": "USD",
        },
    ]


@pytest.mark.regression
def test_entity_resolver_replaces_contradictory_parent_color_with_variant_consensus() -> None:
    record = {
        "color": "Brown",
        "variants": [
            {"sku": "BLACK-8", "size": "8", "color": "Jet Black"},
            {"sku": "BLACK-9", "size": "9", "color": "Jet Black"},
        ],
    }

    resolve_detail_entities(record)

    assert record["color"] == "Jet Black"
    assert record["_transforms"] == [
        {
            "rule_id": "VARIANT_CONSENSUS_TO_PRODUCT",
            "field_name": "color",
            "entity_ref": "product",
            "before": "Brown",
            "after": "Jet Black",
            "evidence_ids": [],
        }
    ]


@pytest.mark.regression
def test_entity_resolver_replaces_symbol_guessed_currency_with_variant_consensus() -> None:
    record = {
        "currency": "USD",
        "variants": [
            {"sku": "CA-8", "size": "8", "currency": "CAD"},
            {"sku": "CA-9", "size": "9", "currency": "CAD"},
        ],
    }

    resolve_detail_entities(record)

    assert record["currency"] == "CAD"
    assert record["_transforms"][0]["before"] == "USD"
    assert record["_transforms"][0]["after"] == "CAD"


@pytest.mark.regression
def test_entity_resolver_converts_negative_inventory_to_explicit_unavailable() -> None:
    record = {
        "variants": [
            {
                "sku": "SILVER",
                "color": "Silver",
                "stock_quantity": -7,
                "availability": "in_stock",
            }
        ]
    }

    resolve_detail_entities(record)

    assert record["variants"][0]["stock_quantity"] == 0
    assert record["variants"][0]["availability"] == "out_of_stock"
    assert {
        transform["field_name"] for transform in record["_transforms"]
    } == {"stock_quantity", "availability"}


@pytest.mark.regression
def test_normalization_drops_related_products_misread_as_volume_variants() -> None:
    record = {
        "title": "Aganice Aromatique Candle",
        "variants": [
            {"size": "16.9 fl oz", "volume": "10.5"},
            {"size": "2.6 oz", "volume": "10.5"},
            {"size": "16.5 oz", "volume": "10.5"},
        ],
    }

    normalize_variant_record(record)

    assert "variants" not in record
    assert record["_transforms"][0]["rule_id"] == "RELATED_VOLUME_ROWS_REMOVED"


@pytest.mark.regression
def test_normalization_collapses_metadata_prefixed_color_aliases() -> None:
    record = {
        "variants": [
            {"size": "S", "color": "Yellow"},
            {"size": "S", "color": "Fncolorname Yellow"},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [{"size": "S", "color": "Yellow"}]
