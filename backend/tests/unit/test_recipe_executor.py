from __future__ import annotations

import ast
from pathlib import Path

from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeBinding,
    RecipeEntity,
    RecipeJoin,
    RecipeScope,
)
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface
from tests.ast_helpers import collect_import_modules


def _recipe(*, product_id: str = "P-RED") -> ExtractionRecipe:
    return ExtractionRecipe(
        recipe_id="detail-v2",
        scope=RecipeScope(
            domain="shop.test",
            surface="ecommerce_detail",
            route_pattern="/products/{id}",
        ),
        capture_requirements=("rendered_dom", "network_json"),
        record_root=RecipeBinding(
            binding_id="record.root",
            source="dom_text",
            path="main[data-product-id]",
            cardinality="one",
            required=True,
        ),
        identity=(
            RecipeBinding(
                binding_id="record.identity.product_id",
                source="dom_attribute",
                path=".",
                attribute="data-product-id",
                field="product_id",
                compare_to="request.product_identity",
                required=True,
            ),
        ),
        entities={
            "selected_variant": RecipeEntity(
                root=RecipeBinding(
                    binding_id="entity.selected_variant",
                    source="dom_text",
                    path="[aria-pressed='true'][data-sku]",
                    scope="record.root",
                    cardinality="one",
                    required=True,
                ),
                identity=(
                    RecipeBinding(
                        binding_id="entity.selected_variant.sku",
                        source="dom_attribute",
                        path=".",
                        attribute="data-sku",
                        field="sku",
                        required=True,
                    ),
                ),
            ),
            "offer": RecipeEntity(
                root=RecipeBinding(
                    binding_id="entity.offer",
                    source="network_json_pointer",
                    artifact="network_0",
                    path="/variants/*",
                    cardinality="many",
                    required=True,
                ),
                joins=(RecipeJoin(left="selected_variant.sku", right="offer.sku"),),
            ),
        },
        fields={
            "title": (
                RecipeBinding(
                    binding_id="field.title",
                    source="dom_text",
                    path="h1",
                    scope="record.root",
                    field="title",
                    transform="normalized_text",
                    required=True,
                ),
            ),
            "sku": (
                RecipeBinding(
                    binding_id="field.sku",
                    source="json_pointer",
                    path="/sku",
                    scope="entity.offer",
                    field="sku",
                    required=True,
                ),
            ),
            "price": (
                RecipeBinding(
                    binding_id="field.price",
                    source="json_pointer",
                    path="/price_minor",
                    scope="entity.offer",
                    field="price",
                    sense="current_public_price",
                    unit="minor",
                    required=True,
                ),
            ),
            "currency": (
                RecipeBinding(
                    binding_id="field.currency",
                    source="json_pointer",
                    path="/currency",
                    scope="entity.offer",
                    field="currency",
                    required=True,
                ),
            ),
            "category": (
                RecipeBinding(
                    binding_id="field.category",
                    source="dom_text",
                    path="[data-product-category]",
                    scope="record.root",
                    field="category",
                    transform="normalized_text",
                ),
            ),
            "image_url": (
                RecipeBinding(
                    binding_id="field.image_url",
                    source="dom_attribute",
                    path="img[data-product-image]",
                    scope="record.root",
                    attribute="src",
                    field="image_url",
                ),
            ),
            "variants": (
                RecipeBinding(
                    binding_id="field.variants",
                    source="json_pointer",
                    path="/",
                    scope="entity.offer",
                    field="variants",
                    cardinality="many",
                ),
            ),
        },
        exclusions=(
            RecipeBinding(
                binding_id="exclude.recommendations",
                source="dom_text",
                path="[data-component='recommendations']",
                scope="record.root",
                cardinality="many",
            ),
        ),
        required=("record.identity", "title", "sku", "price", "currency"),
    )


def _request(*, product_id: str = "P-RED"):
    html = f"""
    <main data-product-id="{product_id}">
      <h1> Trail Shoe Red </h1>
      <button aria-pressed="true" data-sku="SKU-RED">Red</button>
      <nav data-product-category>Trail Shoes</nav>
      <img data-product-image src="https://cdn.shop.test/p-red.jpg">
      <section data-component="recommendations"><h1>Wrong Sibling</h1></section>
    </main>
    """
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        "https://shop.test/products/trail-shoe-red",
        network_payloads=[
            {
                "body": {
                    "variants": [
                        {"sku": "SKU-BLUE", "price_minor": 9999, "currency": "USD"},
                        {"sku": "SKU-RED", "price_minor": 12999, "currency": "USD"},
                    ]
                }
            }
        ],
    )
    return request.model_copy(
        update={"runtime_snapshot": {"product_identity": product_id}}
    )


def test_executor_binds_exact_child_offer_and_typed_price() -> None:
    result = execute_recipe(_request(), _recipe())

    assert result.failure_code is None
    assert result.records == (
        {
            "product_id": "P-RED",
            "title": "Trail Shoe Red",
            "sku": "SKU-RED",
            "price": "129.99",
            "currency": "USD",
            "category": "Trail Shoes",
            "image_url": "https://cdn.shop.test/p-red.jpg",
            "variants": [{"sku": "SKU-RED", "price_minor": 12999, "currency": "USD"}],
        },
    )
    assert {row.binding_id for row in result.outcomes if row.status == "resolved"} >= {
        "record.identity.product_id",
        "field.title",
        "field.sku",
        "field.price",
    }


def test_executor_aggregates_repeated_field_bindings() -> None:
    request = _request()
    html = request.artifact_reader.read_text(request.capture.artifacts[0]).replace(
        "</main>",
        '<img data-product-image-alt src="/p-red-side.jpg"></main>',
    )
    changed = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        request.capture.final_url,
        network_payloads=[
            {"body": request.artifact_reader.read_json(request.capture.artifacts[1])}
        ],
    ).model_copy(update={"runtime_snapshot": {"product_identity": "P-RED"}})
    recipe = _recipe()
    fields = dict(recipe.fields)
    fields["additional_images"] = (
        RecipeBinding(
            binding_id="field.additional_images.primary",
            source="dom_attribute",
            path="img[data-product-image]",
            attribute="src",
            field="additional_images",
            cardinality="many",
        ),
        RecipeBinding(
            binding_id="field.additional_images.side",
            source="dom_attribute",
            path="img[data-product-image-alt]",
            attribute="src",
            field="additional_images",
            cardinality="many",
        ),
    )

    result = execute_recipe(changed, recipe.model_copy(update={"fields": fields}))

    assert result.failure_code is None
    assert result.records[0]["additional_images"] == [
        "https://cdn.shop.test/p-red.jpg",
        "https://shop.test/p-red-side.jpg",
    ]


def test_executor_fails_closed_on_requested_child_mismatch() -> None:
    request = _request(product_id="P-BLUE").model_copy(
        update={"runtime_snapshot": {"product_identity": "P-RED"}}
    )
    result = execute_recipe(request, _recipe())

    assert result.records == ()
    assert result.failure_code == "recipe_identity_mismatch"


def test_executor_fails_closed_when_selected_child_cannot_join_offer() -> None:
    request = _request()
    html = request.artifact_reader.read_text(request.capture.artifacts[0]).replace(
        'data-sku="SKU-RED"', 'data-sku="SKU-GREEN"'
    )
    changed = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        request.capture.final_url,
        network_payloads=[
            {
                "body": {
                    "variants": [
                        {"sku": "SKU-BLUE", "price_minor": 9999, "currency": "USD"}
                    ]
                }
            }
        ],
    ).model_copy(update={"runtime_snapshot": {"product_identity": "P-RED"}})

    result = execute_recipe(changed, _recipe())

    assert result.records == ()
    assert result.failure_code == "recipe_join_failed"


def test_executor_rejects_terminal_shell_without_product_root() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<main><h1>Welcome</h1><nav>Account Search Cart</nav></main>",
        "https://shop.test/products/trail-shoe-red",
        network_payloads=[{"body": {"variants": []}}],
    ).model_copy(update={"runtime_snapshot": {"product_identity": "P-RED"}})

    result = execute_recipe(request, _recipe())

    assert result.records == ()
    assert result.failure_code == "recipe_root_not_found"


def test_executor_has_no_discovery_model_resolver_or_storage_imports() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "core"
        / "extraction_memory"
        / "recipe_executor.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = collect_import_modules(tree)

    assert not any(
        name.startswith(
            (
                "app.extraction.adapters",
                "app.extraction.collectors",
                "app.extraction.model_runtime",
                "app.extraction.resolution",
                "app.models",
                "app.persistence",
            )
        )
        for name in imports
    )


_LISTING_HTML = (
    "<html><body><ul>"
    '<li><a href="/p/1"><h3>Alpha</h3></a><span>$10</span></li>'
    '<li><a href="/p/2"><h3>Beta</h3></a><span>$20</span></li>'
    "</ul></body></html>"
)
_ONE_CARD_HTML = (
    "<html><body><ul>"
    '<li><a href="/p/1"><h3>Alpha</h3></a><span>$10</span></li>'
    "</ul></body></html>"
)


def _listing_recipe(*, min_count: int | None = None) -> ExtractionRecipe:
    root_kwargs: dict[str, object] = dict(
        binding_id="record.root",
        source="dom_text",
        path="ul > li",
        cardinality="many",
        required=True,
    )
    if min_count is not None:
        root_kwargs["min_count"] = min_count
    return ExtractionRecipe(
        recipe_id="listing-v2",
        scope=RecipeScope(
            domain="shop.test",
            surface="ecommerce_listing",
            route_pattern="/c/{id}",
        ),
        capture_requirements=("rendered_dom",),
        record_root=RecipeBinding(**root_kwargs),
        identity=(
            RecipeBinding(
                binding_id="record.identity.url",
                source="dom_attribute",
                path="a",
                attribute="href",
                field="url",
                scope="record.root",
                cardinality="zero_or_one",
                required=True,
            ),
        ),
        fields={
            "url": (
                RecipeBinding(
                    binding_id="field.url",
                    source="dom_attribute",
                    path="a",
                    attribute="href",
                    field="url",
                    scope="record.root",
                    cardinality="zero_or_one",
                ),
            ),
            "title": (
                RecipeBinding(
                    binding_id="field.title",
                    source="dom_text",
                    path="a > h3",
                    field="title",
                    scope="record.root",
                ),
            ),
        },
        required=("record.identity", "url", "title"),
    )


def _listing_request(html: str, *, max_records: int = 10):
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        html,
        "https://shop.test/c/shoes",
        max_records=max_records,
    )


def test_listing_recipe_single_card_root_fails_cardinality() -> None:
    # Finding 7: a listing recipe whose record root grounds to a single card is
    # not a record set; the executor must fail_cardinality even though a lone
    # card would otherwise satisfy the required bindings.
    result = execute_recipe(
        _listing_request(_ONE_CARD_HTML), _listing_recipe(min_count=2)
    )
    assert result.records == ()
    assert result.failure_code == "recipe_cardinality_changed"


def test_listing_recipe_multi_card_passes_even_with_max_records_one() -> None:
    # The raw root count is checked BEFORE the max_records slice, so a
    # max_records=1 request against a genuine multi-card grid still passes.
    result = execute_recipe(
        _listing_request(_LISTING_HTML, max_records=1), _listing_recipe(min_count=2)
    )
    assert result.failure_code is None
    assert len(result.records) == 1


def test_legacy_listing_payload_without_min_count_still_enforced() -> None:
    # A recipe payload compiled before finding 7 carries no min_count (defaults
    # to 1). The executor derives the min-2 listing floor from the request surface
    # + config, so a one-card replay still fails.
    recipe = _listing_recipe(min_count=None)
    assert recipe.record_root.min_count == 1  # legacy default
    result = execute_recipe(_listing_request(_ONE_CARD_HTML), recipe)
    assert result.records == ()
    assert result.failure_code == "recipe_cardinality_changed"
