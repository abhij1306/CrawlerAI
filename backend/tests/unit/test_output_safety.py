from app.core.records.output_safety import (
    public_availability,
    sanitize_materialized_record,
)


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
