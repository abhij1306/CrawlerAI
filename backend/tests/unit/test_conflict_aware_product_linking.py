from __future__ import annotations

import pytest

from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    RequestContext,
    SourceLocator,
)
from app.extraction.entities import _link_products, _owner_product_id, build_entities

pytestmark = pytest.mark.unit


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-conflict-linking",
        run_id=1,
        requested_url="https://shop.test/products/item",
        final_url="https://shop.test/products/item",
        request_context=RequestContext(context_id="ctx-conflict-linking"),
        artifacts=(),
        acquisition_outcome="success",
    )


def _row(
    bundle: CaptureBundle,
    subject: str,
    fact_type: str,
    value: str,
    *,
    collector_id: str = "jsonld",
    metadata: dict[str, object] | None = None,
):
    return evidence(
        bundle,
        "artifact-1",
        collector_id,
        fact_type,
        value,
        SourceLocator(kind="json_pointer", value=f"/{subject}/{fact_type}"),
        hint=EntityHint(entity_type="product"),
        subject_id=subject,
        metadata=metadata or {},
    )


def test_same_title_with_different_urls_and_skus_remains_separate() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.title", "Classic Cap"),
        _row(bundle, "one", "product.url", "https://shop.test/products/cap-one"),
        _row(bundle, "one", "product.sku", "CAP-ONE"),
        _row(bundle, "two", "product.title", "Classic Cap"),
        _row(bundle, "two", "product.url", "https://shop.test/products/cap-two"),
        _row(bundle, "two", "product.sku", "CAP-TWO"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 2


def test_canonical_url_and_matching_sku_merge_product_subjects() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item?variant=1"),
        _row(bundle, "one", "product.sku", "ITEM-1"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item"),
        _row(bundle, "two", "product.sku", "item-1"),
        _row(bundle, "two", "product.title", "Item"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 1


def test_matching_sku_allows_different_url_resources_to_merge() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item-red"),
        _row(bundle, "one", "product.sku", "ITEM-1"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item-blue"),
        _row(bundle, "two", "product.sku", "item-1"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 1


def test_base_product_url_merges_variant_suffix_representation() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "base", "product.title", "Trail Shoe"),
        _row(bundle, "base", "product.brand", "Example Brand"),
        _row(bundle, "base", "product.url", "https://shop.test/products/trail-shoe"),
        _row(bundle, "variant", "product.title", "Trail Shoe"),
        _row(
            bundle,
            "variant",
            "product.url",
            "https://shop.test/products/trail-shoe/SKU-100",
        ),
        _row(bundle, "variant", "product.sku", "SKU-100"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 1
    assert "product.brand" in entities.products[0].attribute_evidence
    assert "product.sku" in entities.products[0].attribute_evidence


def test_product_marker_identity_merges_wrapped_product_url_representation() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle,
            "page",
            "product.url",
            "https://shop.test/preview/p/trail-shoe/product/9984296/color/blue",
            collector_id="url",
        ),
        _row(bundle, "structured", "product.title", "Trail Shoe"),
        _row(
            bundle,
            "structured",
            "product.url",
            "https://shop.test/p/trail-shoe/product/9984296",
        ),
        _row(bundle, "structured", "product.sku", "9984296"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 1
    assert "product.sku" in entities.products[0].attribute_evidence


def test_shared_url_does_not_merge_conflicting_skus() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "one", "product.url", "https://shop.test/products/item"),
        _row(bundle, "one", "product.sku", "ITEM-A"),
        _row(bundle, "two", "product.url", "https://shop.test/products/item?variant=2"),
        _row(bundle, "two", "product.sku", "ITEM-B"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.products) == 2


def test_url_collector_fallback_only_merges_matching_resource() -> None:
    bundle = _bundle()
    rows = (
        _row(bundle, "main", "product.title", "Item"),
        _row(bundle, "main", "product.url", "https://shop.test/products/item"),
        _row(
            bundle,
            "url-only",
            "product.url",
            "https://shop.test/products/other",
            collector_id="url",
        ),
    )

    products = _link_products(rows)

    assert len(products) == 2


def test_url_only_title_overlap_does_not_merge_sibling_brand_product() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle,
            "url",
            "product.url",
            "https://shop.test/products/nike-air-max-90",
            collector_id="url",
        ),
        _row(bundle, "url", "product.title", "Nike Air Max 90", collector_id="url"),
        _row(bundle, "sibling", "product.title", "Nike Dunk Low"),
        _row(bundle, "sibling", "product.brand", "Nike"),
    )

    products = _link_products(rows)

    assert len(products) == 2


def test_jsonld_node_path_difference_does_not_block_url_title_merge() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle,
            "script-one",
            "product.title",
            "Trail Shoe",
            metadata={"jsonld_node_path": "/@graph/0"},
        ),
        _row(
            bundle,
            "script-one",
            "product.url",
            "https://shop.test/products/trail-shoe",
            metadata={"jsonld_node_path": "/@graph/0"},
        ),
        _row(
            bundle,
            "script-two",
            "product.title",
            "Trail Shoe",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
        _row(
            bundle,
            "script-two",
            "product.url",
            "https://shop.test/products/trail-shoe",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
        _row(
            bundle,
            "script-two",
            "product.brand",
            "ExampleCo",
            metadata={"jsonld_node_path": "/@graph/3"},
        ),
    )

    products = _link_products(rows)

    assert len(products) == 1


def test_owner_product_id_rejects_conflicting_parent_products() -> None:
    bundle = _bundle()
    rows = [
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/a/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_subject_id="product-a",
            parent_scope="product",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.url",
            "https://shop.test/products/item?variant=1",
            SourceLocator(kind="json_pointer", value="/b/url"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_subject_id="product-b",
            parent_scope="product",
        ),
    ]

    owner = _owner_product_id(
        rows,
        {"product-a": "entity-a", "product-b": "entity-b"},
        allowed_relations=frozenset({"product_variant"}),
    )

    assert owner is None


def test_explicit_parent_source_subject_alias_links_variant_without_parent_subject() -> (
    None
):
    bundle = _bundle()
    rows = (
        _row(
            bundle, "product-source", "product.url", "https://shop.test/products/item"
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_source_subject_ids=("product-source",),
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.option.size",
            "M",
            SourceLocator(kind="json_pointer", value="/hasVariant/0/size"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            parent_source_subject_ids=("product-source",),
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].product_entity_id == entities.products[0].entity_id


def test_selected_url_state_links_one_matching_orphan_structured_variant() -> None:
    bundle = _bundle()
    product = _row(bundle, "product", "product.url", "https://shop.test/products/item")
    selected_hint = EntityHint(
        entity_type="variant",
        url="https://shop.test/products/item?fit=Classic&style=CI939&color=BR8825",
        option_values={"fit": "Classic", "style": "CI939", "color": "BR8825"},
        selected=True,
    )
    rows = (
        product,
        evidence(
            bundle,
            "artifact-url",
            "url",
            "variant.selected",
            True,
            SourceLocator(kind="url_component", value="selected_variant"),
            hint=selected_hint,
            subject_id="selected-shell",
            parent_subject_id="product",
        ),
        evidence(
            bundle,
            "artifact-url",
            "url",
            "variant.option.fit",
            "Classic",
            SourceLocator(kind="url_component", value="fit"),
            hint=selected_hint,
            subject_id="selected-shell",
            parent_subject_id="product",
        ),
        evidence(
            bundle,
            "artifact-url",
            "url",
            "variant.option.style",
            "CI939",
            SourceLocator(kind="url_component", value="style"),
            hint=selected_hint,
            subject_id="selected-shell",
            parent_subject_id="product",
        ),
        evidence(
            bundle,
            "artifact-url",
            "url",
            "variant.option.color",
            "BR8825",
            SourceLocator(kind="url_component", value="color"),
            hint=selected_hint,
            subject_id="selected-shell",
            parent_subject_id="product",
        ),
        evidence(
            bundle,
            "artifact-jsonld",
            "jsonld",
            "variant.sku",
            "CI939-BR8825",
            SourceLocator(kind="json_pointer", value="/variant/sku"),
            hint=EntityHint(entity_type="variant", sku="CI939-BR8825"),
            subject_id="structured-variant",
            parent_subject_id="unmapped-structured-parent",
        ),
        evidence(
            bundle,
            "artifact-jsonld",
            "jsonld",
            "variant.option.fit",
            "Classic",
            SourceLocator(kind="json_pointer", value="/variant/fit"),
            hint=EntityHint(entity_type="variant", sku="CI939-BR8825"),
            subject_id="structured-variant",
            parent_subject_id="unmapped-structured-parent",
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].selected is True
    assert "sku:CI939-BR8825" in entities.variants[0].identity_keys


def test_selected_variant_group_is_merged_only_once() -> None:
    bundle = _bundle()
    product = _row(bundle, "product", "product.url", bundle.requested_url)
    classic = EntityHint(
        entity_type="variant",
        variant_id="AA",
        url=f"{bundle.requested_url}?fit=Classic",
        option_values={"fit": "Classic"},
        selected=True,
    )
    blue = EntityHint(
        entity_type="variant",
        variant_id="ZZ",
        url=f"{bundle.requested_url}?color=Blue",
        option_values={"color": "Blue"},
        selected=True,
    )

    def variant_row(
        artifact_id: str,
        collector_id: str,
        fact_type: str,
        value: object,
        hint: EntityHint,
        subject_id: str,
    ):
        return evidence(
            bundle,
            artifact_id,
            collector_id,
            fact_type,
            value,
            SourceLocator(kind="json_pointer", value=f"/{subject_id}/{fact_type}"),
            hint=hint,
            subject_id=subject_id,
            parent_subject_id="product",
        )

    rows = (
        product,
        variant_row("url-a", "url", "variant.selected", True, classic, "a"),
        variant_row("url-a", "url", "variant.option.fit", "Classic", classic, "a"),
        variant_row("url-a", "url", "variant.option.color", "Blue", classic, "a"),
        variant_row(
            "json-b",
            "jsonld",
            "variant.sku",
            "Classic-Blue",
            EntityHint(entity_type="variant", variant_id="MM", sku="Classic-Blue"),
            "b",
        ),
        variant_row("url-c", "url", "variant.selected", True, blue, "c"),
        variant_row("url-c", "url", "variant.option.color", "Blue", blue, "c"),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
    assert entities.variants[0].selected is True
    assert "sku:Classic-Blue" in entities.variants[0].identity_keys


def test_evidence_normalizes_ids_and_falls_back_from_invalid_explicit_brand_role() -> (
    None
):
    bundle = _bundle()
    row = evidence(
        bundle,
        "artifact-1",
        "js_state",
        "product.brand",
        "Acme",
        SourceLocator(kind="script_path", value="/product/brand"),
        brand_role="not-a-role",
        metadata={"brand_role": "vendor"},
        source_subject_ids=(" source-a ",),
        parent_source_subject_ids=(" parent-a ",),
        relation_evidence_ids=(" relation-a ",),
    )

    assert row.brand_role == "vendor"
    assert row.source_subject_ids == ("source-a",)
    assert row.parent_source_subject_ids == ("parent-a",)
    assert row.relation_evidence_ids == ("relation-a",)


def test_metadata_parent_alias_is_trimmed_before_linking() -> None:
    bundle = _bundle()
    rows = (
        _row(
            bundle, "product-source", "product.url", "https://shop.test/products/item"
        ),
        evidence(
            bundle,
            "artifact-1",
            "legacy",
            "variant.sku",
            "SKU-1",
            SourceLocator(kind="json_pointer", value="/variant/sku"),
            hint=EntityHint(entity_type="variant", sku="SKU-1"),
            subject_id="variant-1",
            metadata={"parent_source_subject_ids": [" product-source "]},
        ),
    )

    entities = build_entities(bundle, rows)

    assert len(entities.variants) == 1
