from __future__ import annotations

from app.services.js_state.state_normalizer import map_js_state_to_fields


def test_map_js_state_backfills_current_product_color_for_size_variants() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "product": {
                            "id": 9002,
                            "title": "Men's Wool Runner",
                            "handle": "mens-wool-runners-tuke-river",
                            "vendor": "Allbirds",
                            "color": "Tuke River",
                            "options": [{"name": "Size"}],
                            "variants": [
                                {
                                    "id": 17874798313541,
                                    "sku": "WR2MTRV120",
                                    "option1": "12",
                                    "available": False,
                                },
                                {
                                    "id": 17874798346309,
                                    "sku": "WR2MTRV130",
                                    "option1": "13",
                                    "available": False,
                                },
                            ],
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://www.allbirds.com/products/mens-wool-runners-tuke-river",
    )

    assert mapped["color"] == "Tuke River"
    assert [(variant["size"], variant["color"]) for variant in mapped["variants"]] == [
        ("12", "Tuke River"),
        ("13", "Tuke River"),
    ]
