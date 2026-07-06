from __future__ import annotations

import pytest

from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import (
    CaptureBundle,
    EntityHint,
    ExtractionRequest,
    RequestContext,
    SourceLocator,
)
from app.extraction.entities import build_entities
from app.extraction.targeting import scoped_graph, select_commerce_target
from app.extraction.surfaces import surface_spec, Surface

pytestmark = pytest.mark.unit


class _Reader:
    document_store = None

    def read_text(self, artifact):
        raise AssertionError("not used")

    def read_json(self, artifact):
        raise AssertionError("not used")

    def exists(self, artifact_id: str) -> bool:
        return False


def _bundle() -> CaptureBundle:
    return CaptureBundle(
        schema_version="capture.v1",
        bundle_id="bundle-primary-root",
        run_id=1,
        requested_url="https://shop.test/products/primary-cap",
        final_url="https://shop.test/products/primary-cap",
        request_context=RequestContext(context_id="ctx-primary-root"),
        artifacts=(),
        acquisition_outcome="success",
    )


def _product_rows(bundle: CaptureBundle, subject: str, url: str, title: str):
    hint = EntityHint(entity_type="product", url=url)
    return (
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "product.url",
            url,
            SourceLocator(kind="json_pointer", value=f"/{subject}/url"),
            hint=hint,
            subject_id=subject,
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "product.title",
            title,
            SourceLocator(kind="json_pointer", value=f"/{subject}/name"),
            hint=hint,
            subject_id=subject,
        ),
    )


def test_exact_page_url_selects_primary_product_before_child_linking() -> None:
    bundle = _bundle()
    rows = [
        *_product_rows(
            bundle,
            "product-primary",
            "https://shop.test/products/primary-cap?variant=1",
            "Primary Cap",
        ),
        *_product_rows(
            bundle,
            "product-related",
            "https://shop.test/products/related-shirt",
            "Related Shirt",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "CAP-1",
            SourceLocator(kind="json_pointer", value="/primary/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="CAP-1"),
            subject_id="variant-primary",
            parent_subject_id="product-primary",
        ),
        evidence(
            bundle,
            "artifact-1",
            "jsonld",
            "variant.sku",
            "SHIRT-1",
            SourceLocator(kind="json_pointer", value="/related/hasVariant/0/sku"),
            hint=EntityHint(entity_type="variant", sku="SHIRT-1"),
            subject_id="variant-related",
            parent_subject_id="product-related",
        ),
    ]

    entities = build_entities(bundle, tuple(rows))

    assert len(entities.products) == 1
    assert len(entities.variants) == 1
    identity_key = entities.variants[0].identity_key
    assert identity_key == "sku:CAP-1"


def test_ambiguous_roots_remain_unselected_instead_of_arbitrary_choice() -> None:
    bundle = _bundle()
    rows = (
        *_product_rows(
            bundle,
            "product-one",
            "https://shop.test/products/one",
            "One",
        ),
        *_product_rows(
            bundle,
            "product-two",
            "https://shop.test/products/two",
            "Two",
        ),
    )

    entities = build_entities(bundle, tuple(rows))

    assert len(entities.products) == 2


def test_single_wrong_product_root_is_rejected_before_publication() -> None:
    bundle = _bundle()
    rows = (
        *_product_rows(
            bundle,
            "product-related",
            "https://shop.test/products/related-shirt",
            "Related Shirt",
        ),
    )
    entities = build_entities(bundle, rows)
    request = ExtractionRequest(
        surface=Surface.ECOMMERCE_DETAIL,
        capture=bundle,
        artifact_reader=_Reader(),
    )

    target = select_commerce_target(
        entities,
        rows,
        request,
        surface_spec(Surface.ECOMMERCE_DETAIL),
    )
    scoped = scoped_graph(entities, target)

    assert target.status == "missing"
    assert target.rejected_roots[0].reason == "identity_mismatch"
    assert not scoped.products
