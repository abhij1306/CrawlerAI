from app.core.records.output_safety import (
    materialize_product_assets,
    public_availability,
    sanitize_materialized_record,
)
from app.extraction.contracts import AssetDecision


def test_public_availability_only_accepts_canonical_enum_values() -> None:
    assert public_availability("in_stock") == "in_stock"
    assert public_availability("limited_stock") == "limited_stock"
    assert public_availability("https://schema.org/InStock") == ""
    assert public_availability("unknown") == ""


def test_sanitize_record_does_not_repair_title_brand_sku_or_variant_semantics() -> None:
    record = {
        "title": "large",
        "brand": "Fragrance",
        "sku": "45993954607338",
        "availability": "in_stock",
        "variants": [
            {
                "variant_id": "45993954607338",
                "sku": "19468100031",
                "size": "UK 10 UK 10.5 UK 11 UK 11.5",
                "availability": "out_of_stock",
            },
            {
                "sku": "JQ6823",
                "size": "Small",
                "availability": "out_of_stock",
            },
        ],
        "variant_count": 2,
    }
    lineages = {
        "title": {"evidence_ids": ["title"]},
        "brand": {"evidence_ids": ["brand"]},
        "sku": {"evidence_ids": ["sku"]},
        "availability": {"evidence_ids": ["availability"]},
        "variants": [{"sku": {}, "size": {}, "availability": {}}, {}],
    }

    sanitize_materialized_record(record, lineages)

    assert record["title"] == "large"
    assert record["brand"] == "Fragrance"
    assert record["sku"] == "45993954607338"
    assert record["variant_count"] == 2
    assert record["variants"] == [
        {
            "variant_id": "45993954607338",
            "sku": "19468100031",
            "size": "UK 10 UK 10.5 UK 11 UK 11.5",
            "availability": "out_of_stock",
        },
        {
            "sku": "JQ6823",
            "size": "Small",
            "availability": "out_of_stock",
        },
    ]


def test_sanitize_record_enforces_enum_empty_values_and_lineage_shape_only() -> None:
    record = {
        "availability": "https://schema.org/InStock",
        "variants": [
            {
                "sku": "SKU-1",
                "color": "Black",
                "availability": "unknown",
                "size": "",
            },
            {},
            "not-a-row",
        ],
        "variant_count": 3,
    }
    lineages = {
        "availability": {"evidence_ids": ["availability"]},
        "variants": [
            {
                "sku": {"evidence_ids": ["sku"]},
                "color": {"evidence_ids": ["color"]},
                "availability": {"evidence_ids": ["availability"]},
                "size": {"evidence_ids": ["size"]},
            },
            {},
            {},
        ],
    }

    sanitize_materialized_record(record, lineages)

    assert "availability" not in record
    assert record["variants"] == [{"sku": "SKU-1", "color": "Black"}]
    assert record["variant_count"] == 1
    assert lineages["variants"] == [
        {
            "sku": {"evidence_ids": ["sku"]},
            "color": {"evidence_ids": ["color"]},
        }
    ]


def test_sanitize_record_drops_non_actionable_single_axis_variant_rows() -> None:
    record = {
        "variants": [
            {"size": "Small"},
            {"size": "Small", "color": "Black"},
            {"sku": "SKU-1"},
        ],
        "variant_count": 3,
    }
    lineages = {"variants": [{"size": {}}, {"size": {}, "color": {}}, {"sku": {}}]}

    sanitize_materialized_record(record, lineages)

    assert record["variants"] == [
        {"size": "Small", "color": "Black"},
        {"sku": "SKU-1"},
    ]
    assert record["variant_count"] == 2


def test_materialize_product_assets_rejects_conflicting_product_images() -> None:
    record = {
        "title": "Luna Bag",
        "url": "https://shop.test/products/luna-bag",
    }
    lineages: dict[str, object] = {}
    decisions = (
        AssetDecision(
            asset_entity_id="asset-primary",
            url="https://cdn.test/luna-bag-front.jpg",
            accepted_evidence_ids=("primary",),
            role="primary",
        ),
        AssetDecision(
            asset_entity_id="asset-related",
            url="https://cdn.test/nadia-heeled-ballerina.jpg",
            accepted_evidence_ids=("related",),
            role="additional",
        ),
    )

    materialize_product_assets(record, lineages, decisions)

    assert record["image_url"] == "https://cdn.test/luna-bag-front.jpg"
    assert "additional_images" not in record


def test_materialize_product_assets_rejects_conflicting_style_code() -> None:
    record = {
        "title": "40th Anniversary Graphic Womens Short Sleeve Shirt (Black/Red)",
        "url": "https://shop.test/products/jordan-hj0139-045-shirt",
    }
    lineages: dict[str, object] = {}
    decisions = (
        AssetDecision(
            asset_entity_id="wrong-style",
            url="https://cdn.test/title=jordan-hj0139-133-shirt-beige-red.jpg",
            accepted_evidence_ids=("wrong",),
            role="primary",
        ),
    )

    materialize_product_assets(record, lineages, decisions)

    assert "image_url" not in record
