from app.core.records.output_safety import (
    filter_variant_product_family,
    looks_like_size_inventory_blob,
    public_availability,
    sanitize_materialized_record,
)


def test_public_availability_normalizes_schema_urls_and_tokens() -> None:
    assert public_availability("https://schema.org/SoldOut") == "out_of_stock"
    assert public_availability("https://schema.org/InStock") == "in_stock"
    assert public_availability("limited_stock") == "limited_stock"
    assert public_availability("unknown") == ""


def test_size_inventory_blob_is_not_published_as_one_size() -> None:
    assert looks_like_size_inventory_blob("UK 10 UK 10.5 UK 11 UK 11.5")
    assert not looks_like_size_inventory_blob("M 10 / W 11")


def test_variant_family_filter_drops_unrelated_embedded_products() -> None:
    record = {
        "sku": "B-RGW17GWS-VN",
        "url": "https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html",
    }
    rows = [
        {
            "sku": "B-RGW17GWS-VN",
            "color": "Vintage Navy",
            "availability": "out_of_stock",
        },
        {"sku": "JQ6823", "size": "UK 10", "availability": "out_of_stock"},
        {"sku": "JN3708", "size": "Small", "availability": "out_of_stock"},
    ]
    lineages = [{"row": index} for index in range(len(rows))]

    filtered, filtered_lineage = filter_variant_product_family(record, rows, lineages)

    assert filtered == [rows[0]]
    assert filtered_lineage == [lineages[0]]


def test_sanitize_record_removes_generic_brand_and_repairs_variants() -> None:
    record = {
        "brand": "Fragrance",
        "sku": "B-RGW17GWS-VN",
        "url": "https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html",
        "availability": "https://schema.org/SoldOut",
        "variant_count": 3,
        "variants": [
            {
                "sku": "B-RGW17GWS-VN",
                "color": "Vintage Navy",
                "availability": "https://schema.org/SoldOut",
            },
            {
                "sku": "JQ6823",
                "size": "UK 10 UK 10.5 UK 11 UK 11.5",
                "availability": "https://schema.org/SoldOut",
            },
            {
                "sku": "JN3708",
                "size": "Small Medium Large X-Large",
                "availability": "https://schema.org/SoldOut",
            },
        ],
    }
    lineages = {"brand": {}, "availability": {}, "variants": [{}, {}, {}]}

    sanitize_materialized_record(record, lineages)

    assert "brand" not in record
    assert record["availability"] == "out_of_stock"
    assert record["variant_count"] == 1
    assert record["variants"] == [
        {
            "sku": "B-RGW17GWS-VN",
            "color": "Vintage Navy",
            "availability": "out_of_stock",
        }
    ]


def test_variant_lineage_matches_sanitized_variant_fields() -> None:
    record = {
        "variants": [
            {
                "sku": "SKU-1",
                "size": "UK 10 UK 10.5 UK 11 UK 11.5",
                "availability": "unknown",
                "color": "Black",
            }
        ],
        "variant_count": 1,
    }
    lineages = {
        "variants": [
            {
                "sku": {"evidence_ids": ["sku"]},
                "size": {"evidence_ids": ["size"]},
                "availability": {"evidence_ids": ["availability"]},
                "color": {"evidence_ids": ["color"]},
            }
        ]
    }

    sanitize_materialized_record(record, lineages)

    assert record["variants"] == [{"sku": "SKU-1", "color": "Black"}]
    assert lineages["variants"] == [
        {
            "sku": {"evidence_ids": ["sku"]},
            "color": {"evidence_ids": ["color"]},
        }
    ]


def test_sanitize_recovers_url_title_and_parent_sku() -> None:
    record = {
        "title": "large",
        "url": "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        "sku": "45993954607338",
        "variants": [
            {
                "variant_id": "45993954607338",
                "sku": "19468100031",
                "size": "11",
                "availability": "in_stock",
            }
        ],
        "variant_count": 1,
    }
    lineages = {"title": {}, "sku": {}, "variants": [{}]}

    sanitize_materialized_record(record, lineages)

    assert record["title"] == "Rustic Cotton T Shirt"
    assert record["sku"] == "19468100031"


def test_sanitize_drops_ambiguous_repeated_size_inventory() -> None:
    record = {
        "url": "https://example.com/product",
        "variants": [
            {"size": size, "sku": f"sku-{index}"}
            for index, size in enumerate(["S", "M", "L", "S", "M", "L", "S", "M", "L"])
        ],
        "variant_count": 9,
    }
    lineages = {"variants": [{} for _ in range(9)]}

    sanitize_materialized_record(record, lineages)

    assert "variants" not in record
    assert "variant_count" not in record
