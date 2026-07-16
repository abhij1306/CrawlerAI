from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.core.extraction_memory.recipe_contracts import (
    BindingOutcome,
    DiscoveryResult,
    ExtractionRecipe,
    RecipeBinding,
    RecipeCandidate,
    RecipeEntity,
    RecipeExecutionResult,
    RecipeJoin,
    RecipeScope,
)
from app.extraction.contracts import ExtractionResult, StageOutcome
from app.observability.diagnose import build_diagnosis
from tests.ast_helpers import collect_import_modules

pytestmark = pytest.mark.unit
APP_ROOT = Path(__file__).resolve().parents[2] / "app"
CONTRACT_PATH = APP_ROOT / "core" / "extraction_memory" / "recipe_contracts.py"


def _recipe() -> ExtractionRecipe:
    return ExtractionRecipe(
        recipe_id="recipe-1",
        scope=RecipeScope(
            domain="shop.test",
            surface="ecommerce_detail",
            route_pattern="/products/{id}",
        ),
        capture_requirements=("rendered_dom",),
        record_root=RecipeBinding(
            binding_id="record.root",
            source="dom_text",
            path="main[data-product-id]",
            cardinality="one",
            required=True,
        ),
        identity=(
            RecipeBinding(
                binding_id="record.identity",
                source="dom_attribute",
                path="main[data-product-id]",
                attribute="data-product-id",
                compare_to="request.product_identity",
                required=True,
            ),
        ),
        entities={
            "offer": RecipeEntity(
                root=RecipeBinding(
                    binding_id="entity.offer",
                    source="network_json_pointer",
                    artifact="product_api",
                    path="/variants/*",
                    cardinality="many",
                ),
                joins=(RecipeJoin(left="selected_variant.sku", right="offer.sku"),),
            )
        },
        fields={
            "title": (
                RecipeBinding(
                    binding_id="field.title",
                    source="dom_text",
                    path="h1",
                    required=True,
                ),
            ),
            "price": (
                RecipeBinding(
                    binding_id="field.price",
                    source="json_pointer",
                    path="/price/current",
                    scope="entity.offer",
                    sense="current_public_price",
                    unit="major",
                ),
            ),
        },
        exclusions=(
            RecipeBinding(
                binding_id="exclude.recommendations",
                source="dom_text",
                path="[data-component='recommendations']",
                cardinality="many",
            ),
        ),
    )


def test_recipe_contract_covers_frozen_primitives() -> None:
    recipe = _recipe()

    assert recipe.schema_version == "extraction_recipe.v2"
    assert recipe.record_root.cardinality == "one"
    assert recipe.identity[0].compare_to == "request.product_identity"
    assert recipe.entities["offer"].joins[0].right == "offer.sku"
    assert recipe.fields["price"][0].sense == "current_public_price"
    assert recipe.exclusions[0].path.endswith("recommendations']")


def test_recipe_rejects_ungrounded_or_ambiguous_bindings() -> None:
    with pytest.raises(ValidationError):
        RecipeBinding(binding_id="field.title", source="dom_text", path="")
    with pytest.raises(ValidationError):
        RecipeBinding(binding_id="field.sku", source="dom_attribute", path="[data-sku]")
    with pytest.raises(ValidationError):
        RecipeBinding(
            binding_id="field.price",
            source="network_json_pointer",
            path="/price",
        )


def test_discovery_returns_candidate_or_typed_failure_never_both() -> None:
    candidate = RecipeCandidate(
        candidate_id="candidate-1",
        recipe=_recipe(),
        origin="deterministic",
        grounded_paths=("main[data-product-id]", "h1"),
    )

    assert DiscoveryResult(candidate=candidate).candidate is candidate
    assert (
        DiscoveryResult(failure_code="recipe_root_not_found").failure_code
        == "recipe_root_not_found"
    )
    with pytest.raises(ValidationError):
        DiscoveryResult()
    with pytest.raises(ValidationError):
        DiscoveryResult(candidate=candidate, failure_code="recipe_root_not_found")


def test_execution_result_is_internal_values_and_binding_outcomes() -> None:
    result = RecipeExecutionResult(
        recipe_id="recipe-1",
        records=({"title": "Trail Shoe"},),
        outcomes=(
            BindingOutcome(
                binding_id="field.title",
                status="resolved",
                source_path="html:main>h1",
                value="Trail Shoe",
            ),
        ),
    )

    assert result.records == ({"title": "Trail Shoe"},)
    assert result.outcomes[0].source_path == "html:main>h1"


def test_recipe_contract_owner_has_no_runtime_or_publication_imports() -> None:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    imports = collect_import_modules(tree)

    assert not any(
        name.startswith(
            (
                "app.extraction",
                "app.persistence",
                "app.models",
                "app.connectors",
            )
        )
        for name in imports
    )


def test_active_recipe_selection_matches_release_v2_route() -> None:
    selected = select_active_recipe(
        {
            "schema_version": "release.v2",
            "surface": "ecommerce_detail",
            "templates": [
                {
                    "compiled_recipe_id": "compiled-1",
                    "route_pattern": "/products/{slug}",
                    "compiled_recipe": {"schema_version": "extraction_recipe.v2"},
                }
            ],
        },
        surface="ecommerce_detail",
        url="https://shop.test/products/trail-shoe",
    )

    assert selected is not None
    assert selected["compiled_recipe_id"] == "compiled-1"


def test_active_recipe_selection_rejects_legacy_release() -> None:
    selected = select_active_recipe(
        {"surface": "ecommerce_detail", "templates": []},
        surface="ecommerce_detail",
        url="https://shop.test/products/trail-shoe",
    )

    assert selected is None


def test_diagnosis_exposes_recipe_execution_causally() -> None:
    candidate = RecipeCandidate(
        candidate_id="candidate-1",
        recipe=_recipe(),
        origin="deterministic",
        grounded_paths=("dom:#product",),
    )
    result = ExtractionResult(
        surface="ecommerce_detail",
        bundle_id="bundle-1",
        records=(),
        verdict="empty",
        recipe_candidate=candidate,
        recipe_execution=RecipeExecutionResult(
            recipe_id="recipe-1",
            failure_code="recipe_binding_not_found",
            outcomes=(
                BindingOutcome(
                    binding_id="record.title",
                    status="missing",
                    source_path="dom:h1",
                ),
            ),
        ),
        stage_outcomes=(
            StageOutcome(stage="recipe_select", outcome="no_match"),
            StageOutcome(stage="recipe_discovery", outcome="ran"),
            StageOutcome(stage="candidate_recipe_execute", outcome="failed"),
        ),
    )

    diagnosis = build_diagnosis(
        acquisition_result=SimpleNamespace(
            browser_diagnostics={},
            acquisition_diagnostics={},
            status_code=200,
            final_url="https://shop.test/products/1",
            method="http",
        ),
        extraction_result=result,
    )

    assert diagnosis["recipe"] == {
        "selected": False,
        "candidate": {
            "candidate_id": "candidate-1",
            "origin": "deterministic",
            "recipe_id": "recipe-1",
            "grounded_path_count": 1,
        },
        "execution": {
            "recipe_id": "recipe-1",
            "failure_code": "recipe_binding_not_found",
            "detail": None,
            "record_count": 0,
            "binding_outcomes": [
                {
                    "binding_id": "record.title",
                    "status": "missing",
                    "source_path": "dom:h1",
                    "detail": None,
                }
            ],
        },
        "discovery_stages": [
            {"stage": "recipe_select", "outcome": "no_match", "detail": None},
            {"stage": "recipe_discovery", "outcome": "ran", "detail": None},
            {
                "stage": "candidate_recipe_execute",
                "outcome": "failed",
                "detail": None,
            },
        ],
    }
