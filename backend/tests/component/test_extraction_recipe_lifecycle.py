from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_PROVISIONAL,
    EXTRACTION_MEMORY_STATUS_RETIRED,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
)
from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeBinding,
    RecipeCandidate,
    RecipeScope,
)
from app.persistence.extraction_memory import ensure_template
from app.persistence.extraction_recipe_lifecycle import (
    build_executable_release_payload,
    create_executable_release_snapshot,
    record_candidate_validation,
    record_recipe_drift,
    save_recipe_candidate,
)

pytestmark = pytest.mark.component


def _candidate(*, suffix: str = "v1") -> RecipeCandidate:
    recipe = ExtractionRecipe(
        recipe_id=f"detail-{suffix}",
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
                binding_id="record.identity.url",
                source="dom_attribute",
                path="a[data-canonical-product]",
                attribute="href",
                field="url",
                compare_to="request.final_url",
                required=True,
            ),
        ),
        fields={
            "title": (
                RecipeBinding(
                    binding_id="field.title",
                    source="dom_text",
                    path=f"h1[data-version='{suffix}']",
                    field="title",
                    required=True,
                ),
            )
        },
        required=("record.identity", "title"),
    )
    return RecipeCandidate(
        candidate_id=f"candidate-{suffix}",
        recipe=recipe,
        origin="deterministic",
        sample_urls=(f"https://shop.test/products/{suffix}",),
        grounded_paths=(f"h1[data-version='{suffix}']",),
    )


async def _template(session: AsyncSession):
    return await ensure_template(
        session,
        domain="shop.test",
        surface="ecommerce_detail",
        fingerprint="product-page",
        route_pattern="/products/{id}",
    )


@pytest.mark.asyncio
async def test_distinct_samples_promote_and_freeze_release(
    db_session: AsyncSession,
) -> None:
    template = await _template(db_session)
    recipe, compiled = await save_recipe_candidate(
        db_session, template=template, candidate=_candidate()
    )

    assert recipe.status == EXTRACTION_MEMORY_STATUS_PROVISIONAL
    assert compiled.status == EXTRACTION_MEMORY_STATUS_PROVISIONAL
    assert not await record_candidate_validation(
        db_session,
        compiled=compiled,
        sample_url="https://shop.test/products/a",
        succeeded=True,
    )
    assert await record_candidate_validation(
        db_session,
        compiled=compiled,
        sample_url="https://shop.test/products/b",
        succeeded=True,
    )
    assert recipe.status == EXTRACTION_MEMORY_STATUS_ACTIVE
    assert compiled.status == EXTRACTION_MEMORY_STATUS_ACTIVE

    release = await build_executable_release_payload(
        db_session, domain="shop.test", surface="ecommerce_detail"
    )
    assert release["schema_version"] == "release.v2"
    assert release["templates"][0]["compiled_recipe_id"] == str(compiled.id)
    snapshot = await create_executable_release_snapshot(
        db_session, domain="shop.test", surface="ecommerce_detail"
    )
    frozen_payload = deepcopy(snapshot.payload)

    _recipe2, compiled2 = await save_recipe_candidate(
        db_session, template=template, candidate=_candidate(suffix="v2")
    )
    assert await record_candidate_validation(
        db_session,
        compiled=compiled2,
        sample_url="https://shop.test/products/operator-reviewed",
        succeeded=True,
        explicit_approval=True,
    )
    assert compiled.status == EXTRACTION_MEMORY_STATUS_RETIRED
    assert compiled2.status == EXTRACTION_MEMORY_STATUS_ACTIVE
    assert snapshot.payload == frozen_payload
    assert snapshot.payload["templates"][0]["compiled_recipe_id"] == str(compiled.id)


@pytest.mark.asyncio
async def test_distinct_typed_failures_suspend_active_recipe(
    db_session: AsyncSession,
) -> None:
    template = await _template(db_session)
    recipe, compiled = await save_recipe_candidate(
        db_session, template=template, candidate=_candidate()
    )
    await record_candidate_validation(
        db_session,
        compiled=compiled,
        sample_url="https://shop.test/products/approved",
        succeeded=True,
        explicit_approval=True,
    )

    assert not await record_recipe_drift(
        db_session,
        compiled=compiled,
        sample_url="https://shop.test/products/drift-a",
        failure_code="recipe_root_not_found",
    )
    assert await record_recipe_drift(
        db_session,
        compiled=compiled,
        sample_url="https://shop.test/products/drift-b",
        failure_code="recipe_identity_mismatch",
    )
    assert recipe.status == EXTRACTION_MEMORY_STATUS_SUSPENDED
    assert compiled.status == EXTRACTION_MEMORY_STATUS_SUSPENDED
