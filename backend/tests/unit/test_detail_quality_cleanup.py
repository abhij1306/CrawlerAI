from __future__ import annotations

import pytest

from app.services.dom.image_extraction import dedupe_image_urls
from app.services.extract.detail.assembly.final_cleanup import (
    repair_ecommerce_detail_record_quality,
)
from app.services.extract.detail.text.sanitizer import sanitize_detail_long_text


def _repair(record: dict[str, object], page_url: str) -> dict[str, object]:
    repair_ecommerce_detail_record_quality(record, html="", page_url=page_url)
    return record


@pytest.mark.unit
def test_shopify_detail_images_dedupe_keeps_distinct_store_scopes() -> None:
    images = dedupe_image_urls(
        [
            "https://sneakerpolitics.com/cdn/shop/files/item-2.jpg?v=1",
            "https://cdn.shopify.com/s/files/1/0214/7974/files/item-2.jpg?v=1",
            "https://sneakerpolitics.com/cdn/shop/files/item-3.jpg?v=1&width=2000",
            "https://cdn.shopify.com/s/files/1/0214/7974/files/item-3.jpg?v=1",
        ]
    )

    assert len(images) == 4  # nosec B101


@pytest.mark.unit
def test_detail_image_family_rejects_other_colorway_codes() -> None:
    record: dict[str, object] = {
        "title": "Men's Nano Puff Jacket",
        "color": "Aquatic Blue",
        "image_url": "https://www.patagonia.com/images/hi-res/84213_AQT.jpg",
        "additional_images": [
            "https://www.patagonia.com/images/hi-res/84213_AQT_CDD1.jpg",
            "https://www.patagonia.com/images/hi-res/84213_BLK.jpg",
            "https://www.patagonia.com/images/hi-res/84213_SMDB.jpg",
        ],
    }

    _repair(
        record,
        "https://www.patagonia.com/product/mens-nano-puff-insulated-jacket/84213.html",
    )

    assert record["additional_images"] == [  # nosec B101
        "https://www.patagonia.com/images/hi-res/84213_AQT_CDD1.jpg"
    ]


@pytest.mark.unit
def test_detail_record_cleanup_repairs_brand_title_tables_variants_and_discount() -> (
    None
):
    record: dict[str, object] = {
        "brand": "Old",
        "title": "+ Old Skool Shoe - silver - One Size; + Old Skool Shoe - silver - One Size",
        "category": "Mens Shoes",
        "size": "1",
        "price": "249.99",
        "original_price": "249.99",
        "sale_price": "27.00",
        "description": (
            "Footnote 1. 36 Please check the measurements below Chest 60cm "
            "36 Please check the measurements below Waist 39cm lnstagram @seller"
        ),
        "tables": [
            {
                "context": "Size Guide",
                "headers": [" eu_it ", "uk", "us", "ferragamo"],
                "rows": [{"uk": "2", "us": "5", " eu_it ": "35", "ferragamo": "4.5"}],
            }
        ],
        "variants": [
            {"url": "https://example.com/p?variant=1", "color": "White"},
            {"url": "https://example.com/p?variant=1", "color": "Blue"},
            {"size": "Qty.", "availability": "out_of_stock"},
        ],
    }

    _repair(
        record,
        "https://www.vans.com/en-us/p/shoes/icons/old-skool-5205/old-skool-VN000E9TBPG",
    )

    assert record["brand"] == "Vans"  # nosec B101
    assert record["title"] == "Old Skool Shoe"  # nosec B101
    assert "size" not in record  # nosec B101
    assert "sale_price" not in record  # nosec B101
    assert "description" in record  # nosec B101
    description = str(record["description"])
    assert "Footnote" not in description  # nosec B101
    assert "lnstagram" not in description  # nosec B101
    assert description.count("Please check the measurements below") == 1  # nosec B101
    assert record["tables"] == [  # nosec B101
        {
            "context": "Size Guide",
            "headers": ["eu_it", "uk", "us"],
            "rows": [{"eu_it": "35", "uk": "2", "us": "5"}],
        }
    ]
    assert record["variants"] == [  # nosec B101
        {"color": "White"},
        {"color": "Blue"},
    ]


@pytest.mark.unit
def test_missing_numeric_brand_can_be_repaired_from_title_and_url() -> None:
    record: dict[str, object] = {
        "title": "47 NY Yankees Clean Up Cap",
        "price": "35.00",
    }

    _repair(
        record,
        "https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html",
    )

    assert record["brand"] == "47"  # nosec B101


@pytest.mark.unit
def test_numeric_title_prefix_is_not_promoted_to_brand_without_allowlist() -> None:
    record: dict[str, object] = {"title": "123 Example Jacket", "price": "99.00"}

    _repair(record, "https://example.com/products/123-example-jacket")

    assert "brand" not in record  # nosec B101


@pytest.mark.unit
def test_title_cleanup_removes_empty_sanitized_title() -> None:
    record: dict[str, object] = {"title": "+", "_field_sources": {"title": ["dom"]}}

    _repair(record, "https://example.com/products/example")

    assert "title" not in record  # nosec B101
    assert "title" not in record["_field_sources"]  # nosec B101


@pytest.mark.unit
def test_long_text_cleanup_keeps_later_title_mentions_and_only_extra_prompts() -> None:
    text = (
        "Example Jacket is cut from cotton. "
        "The Example Jacket returns this season with a relaxed fit."
    )

    assert sanitize_detail_long_text(text, title="Example Jacket") == text  # nosec B101
    assert (  # nosec B101
        sanitize_detail_long_text(
            "Details Please check the measurements below Model is 6 ft "
            "Please check the measurements below Cotton shell.",
            title="Example Jacket",
        )
        == "Details Please check the measurements below Model is 6 ft Cotton shell."
    )


@pytest.mark.unit
def test_detail_cleanup_trims_repeated_title_blocks_and_sku_title_prefix() -> None:
    sweetwater: dict[str, object] = {
        "brand": "Sony",
        "title": "Wh1Kxm5Blk Sony Wh 1000Xm5 Wireless Noise Canceling Headphones Black",
    }
    lvr: dict[str, object] = {
        "brand": "Barrow",
        "title": "Nylon tank top - Barrow - Boys | Luisaviaroma",
        "description": (
            "Nylon tank top - Barrow - Boys - Logo details - Composition: 100% Polyester - Item code: 83I-UKD027 "
            "Nylon tank top - Barrow - Boys - Green - 12Y - Logo details"
        ),
    }

    _repair(
        sweetwater,
        "https://www.sweetwater.com/store/detail/WH1kXM5BlkBn1--sony-wh-1000xm5-wireless-noise-canceling-headphones",
    )
    _repair(lvr, "https://www.luisaviaroma.com/en-in/p/barrow/kids-boys/83I-UKD027")

    assert (  # nosec B101
        sweetwater["title"]
        == "Sony Wh 1000Xm5 Wireless Noise Canceling Headphones Black"
    )
    assert lvr["description"] == (  # nosec B101
        "Nylon tank top - Barrow - Boys - Logo details - Composition: 100% Polyester - Item code: 83I-UKD027"
    )
