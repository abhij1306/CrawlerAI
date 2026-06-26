from __future__ import annotations

import pytest

from app.extraction.collectors.js_state import path_is_within_selected_root
from app.extraction.collectors.js_state import selected_product_root_paths

from app.extraction.collectors.js_state import network_row
from app.extraction.contracts import CaptureBundle, RequestContext

from app.core.records.js_state_scope import path_product_identity_conflicts

pytestmark = pytest.mark.unit


def test_exact_url_selects_matching_root() -> None:
    objects = (
        (
            "/products/0",
            {
                "type": "Product",
                "url": "https://shop.test/products/primary?variant=1",
            },
        ),
        ("/products/0/variants/0", {"sku": "PRIMARY-1"}),
        ("/products/1", {"url": "https://shop.test/products/related"}),
        ("/products/1/variants/0", {"sku": "RELATED-1"}),
    )
    selected = selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    )
    assert selected == ("/products/0",)
    assert path_is_within_selected_root("/products/0/variants/0", selected)
    assert not path_is_within_selected_root("/products/1/variants/0", selected)


def test_missing_exact_root_keeps_fallback_behavior() -> None:
    objects = (("/product", {"title": "No URL"}),)
    selected = selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    )
    assert selected == ()
    assert path_is_within_selected_root("/product", selected)


def test_metadata_url_match_is_not_selected_as_product_root() -> None:
    objects = (
        (
            "/seo",
            {"canonicalUrl": "https://shop.test/products/primary"},
        ),
        (
            "/product",
            {"type": "Product", "title": "Primary"},
        ),
    )

    assert (
        selected_product_root_paths(objects, "https://shop.test/products/primary") == ()
    )


def test_nested_variant_url_promotes_to_product_ancestor() -> None:
    objects = (
        (
            "/product",
            {"type": "Product", "title": "Primary", "sku": "BASE"},
        ),
        (
            "/product/hasVariant/0",
            {
                "type": "ProductModel",
                "url": "https://shop.test/products/primary?variant=1",
                "sku": "SKU-1",
            },
        ),
    )

    assert selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    ) == ("/product",)


def test_search_hit_rows_are_not_treated_as_product_variants() -> None:
    bundle = CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-search-hit",
        run_id=1,
        requested_url="https://shop.test/products/primary",
        final_url="https://shop.test/products/primary",
        request_context=RequestContext(context_id="ctx-search-hit"),
        artifacts=(),
        acquisition_outcome="success",
    )

    rows = network_row(
        bundle,
        "artifact-search",
        "/results/0/hits/0",
        {
            "sku": "UNRELATED-SKU",
            "size": "Small Medium Large",
            "color": "Black",
        },
        collector_id="network",
    )

    assert rows == []


def test_normalized_cache_item_path_must_match_detail_url_identity() -> None:
    page_url = "https://shop.test/product/dp/141791"

    assert not path_product_identity_conflicts(
        page_url,
        "/props/pageProps/__APOLLO_STATE__/Item:SXRlbToxNDE3OTE=/description",
    )
    assert path_product_identity_conflicts(
        page_url,
        "/props/pageProps/__APOLLO_STATE__/Item:SXRlbToxNDE3ODM=/description",
    )
    assert path_product_identity_conflicts(
        page_url,
        "/props/pageProps/__APOLLO_STATE__/Item:SXRlbToxNDE3OTE=/nested/Item:SXRlbToxNDE3ODM=/description",
    )


def test_structured_recommendation_and_iconography_paths_are_noise() -> None:
    bundle = CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-structured-noise",
        run_id=1,
        requested_url="https://shop.test/product/dp/141791",
        final_url="https://shop.test/product/dp/141791",
        request_context=RequestContext(context_id="ctx-structured-noise"),
        artifacts=(),
        acquisition_outcome="success",
    )

    assert (
        network_row(
            bundle,
            "artifact-state",
            "/ROOT_QUERY/carousel/listings/0/item",
            {"name": "Unrelated recommended product"},
        )
        == []
    )
    assert (
        network_row(
            bundle,
            "artifact-state",
            "/__APOLLO_STATE__/Product:parent/iconography/0",
            {"name": "Grain-Free"},
        )
        == []
    )
