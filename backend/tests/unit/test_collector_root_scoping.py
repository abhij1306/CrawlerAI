from __future__ import annotations

import pytest

from app.extraction.collectors.js_state import network_row
from app.extraction.contracts import CaptureBundle, RequestContext

from app.core.records.js_state_scope import (
    RootSelection,
    path_is_within_selected_root,
    path_product_identity_conflicts,
    root_admits_path,
    select_product_roots,
    selected_product_root_paths,
)

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


def test_single_product_context_selects_without_url_match() -> None:
    # Exactly one product-context object on the page selects, even with no URL
    # agreement — there is no competing root, so admitting it is unambiguous.
    objects = (("/product", {"type": "Product", "title": "No URL"}),)
    selection = select_product_roots(objects, "https://shop.test/products/primary")
    assert selection == RootSelection("selected", ("/product",))
    assert root_admits_path(selection, "/product")


def test_no_product_root_defers_to_per_row_guards() -> None:
    # No product-context object at all (e.g. a bare config/variant payload whose
    # identity is the page itself). The gate stays open and the collector's own
    # per-row conflict guards decide — strict scoping here would discard the only
    # payload on the page.
    objects = (("/config/flags", {"featureEnabled": True}),)
    selection = select_product_roots(objects, "https://shop.test/products/primary")
    assert selection == RootSelection("unresolved", ())
    assert root_admits_path(selection, "/config/flags")
    # An empty root set never matches via the strict containment helper itself.
    assert not path_is_within_selected_root("/config/flags", selection.roots)


def test_competing_product_roots_are_ambiguous_and_admit_nothing() -> None:
    # Two unrelated top-level product contexts and neither matches the page URL:
    # selecting either would be a guess, so admit nothing.
    objects = (
        ("/productA", {"type": "Product", "title": "Alpha"}),
        ("/productB", {"type": "Product", "title": "Bravo"}),
    )
    selection = select_product_roots(objects, "https://shop.test/products/primary")
    assert selection.status == "ambiguous"
    assert selection.roots == ()
    assert not root_admits_path(selection, "/productA")


def test_recommendation_carousel_does_not_create_ambiguity() -> None:
    # A real product plus a recommendation carousel under a noise path: the
    # carousel is excluded from root counting so the real product still selects.
    objects = (
        ("/product", {"type": "Product", "title": "Primary"}),
        ("/recommendations/0", {"type": "Product", "title": "Suggested"}),
    )
    selection = select_product_roots(objects, "https://shop.test/products/primary")
    assert selection == RootSelection("selected", ("/product",))
    assert not root_admits_path(selection, "/recommendations/0")


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

    # The SEO object matches the page URL but carries no product context, so it
    # is never promoted to a root; the real product context is what selects.
    selection = select_product_roots(objects, "https://shop.test/products/primary")
    assert selection == RootSelection("selected", ("/product",))
    assert not root_admits_path(selection, "/seo")


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


def test_nested_offer_url_promotes_to_top_level_product_root() -> None:
    objects = (
        (
            "",
            {
                "@type": "Product",
                "name": "Linen Taper Pants",
                "brand": {"@type": "Brand", "name": "Clothier"},
            },
        ),
        (
            "/offers/0",
            {
                "@type": "Offer",
                "url": "https://shop.test/product.do?pid=8878350120002",
                "sku": "8878350120002",
            },
        ),
    )

    selection = select_product_roots(
        objects, "https://shop.test/product.do?pid=887835012"
    )

    assert selection == RootSelection("selected", ("",))
    assert root_admits_path(selection, "/offers/0")


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
