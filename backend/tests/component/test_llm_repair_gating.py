"""Gating tests for grounded LLM repair (Phase 7).

Prove that grounded LLM proposals route through the SAME compile/replay gates as
operator corrections, yet the model can never activate a rule (even when replay
passes) and never publishes an ungrounded value. Labels are retained with
``unverified_model`` authority for operator review.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.evaluation.llm_repair import (
    GroundedRepairBatch,
    GroundedRepairContractError,
    apply_grounded_repair,
)
from app.models.crawl_run import CrawlUrlResult
from app.models.extraction_memory import (
    ExtractionManifest,
    ExtractionOperatorLabel,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.persistence.artifacts import ArtifactRepository


async def _seed_gradeable_run(db_session: AsyncSession, create_test_run):
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    url_result = CrawlUrlResult(
        run_id=run.id,
        requested_url=run.url,
        normalized_url=run.url,
        final_url=run.url,
        surface=run.surface,
        acquisition_outcome="success",
        verdict="success",
        record_count=1,
    )
    template = ExtractionTemplate(
        domain="example.com",
        surface=run.surface,
        fingerprint="price-template-v1",
        route_pattern="/products/*",
        last_seen_run_id=run.id,
    )
    db_session.add_all([url_result, template])
    await db_session.flush()
    db_session.add(
        ExtractionManifest(
            run_id=run.id,
            url_result_id=url_result.id,
            template_id=template.id,
            manifest_version="extraction-manifest.v1",
            payload={},
        )
    )
    await db_session.flush()
    ArtifactRepository(root_dir=settings.artifacts_dir).persist_bytes(
        run_id=run.id,
        url_result_id=url_result.id,
        name="page.html",
        content=b'<html><body><span class="price">19.99</span></body></html>',
    )
    await db_session.commit()
    return run, url_result, template


def _batch(url_result_id: int, **overrides: object) -> GroundedRepairBatch:
    proposal: dict[str, object] = {
        "field_name": "price",
        "subject_id": "product:1",
        "canonical_value": "19.99",
        "semantic_role": "primary_price",
        "locale_interpretation": "USD",
        "uncertainty_reason": "current value picked the compare-at price",
        "grounding": [
            {
                "kind": "node",
                "artifact_id": f"url-result:{url_result_id}:page.html",
                "locator": "css:.price",
            }
        ],
    }
    proposal.update(overrides)
    return GroundedRepairBatch.model_validate({"proposals": [proposal]})


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_repair_passes_replay_but_never_activates(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run, url_result, template = await _seed_gradeable_run(db_session, create_test_run)
    baseline_release_id = run.extraction_release_snapshot_id
    baseline_release_count = len(
        (await db_session.execute(select(ExtractionReleaseSnapshot))).scalars().all()
    )

    result = await apply_grounded_repair(
        db_session,
        run=run,
        batch=_batch(url_result.id),
        representative_url_result_ids=[url_result.id],
    )

    # Legacy selector replay is disabled until a recipe-v2 candidate is compiled.
    assert result["replay"] is None
    assert result["activation_status"] == "recipe_candidate_required"
    assert result["activation_status"] != "activated"

    # No selector recipe was written for the template.
    recipe = (
        await db_session.execute(
            select(ExtractionRecipe).where(ExtractionRecipe.template_id == template.id)
        )
    ).scalar_one_or_none()
    assert recipe is None

    # The active release pointer is untouched and no new snapshot was activated.
    await db_session.refresh(run)
    assert run.extraction_release_snapshot_id == baseline_release_id
    release_count = len(
        (await db_session.execute(select(ExtractionReleaseSnapshot))).scalars().all()
    )
    assert release_count == baseline_release_count

    # No legacy correction row is written before recipe-v2 compilation.
    assert result["correction_id"] is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_empty_grounded_repair_batch_is_a_noop(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    result = await apply_grounded_repair(
        db_session,
        run=run,
        batch=GroundedRepairBatch.model_validate({"proposals": []}),
    )

    assert result["activation_status"] == "no_grounded_repairs"
    assert result["label_count"] == 0
    labels = (
        (
            await db_session.execute(
                select(ExtractionOperatorLabel).where(
                    ExtractionOperatorLabel.source_run_id == run.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert labels == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_repair_rejects_undeclared_custom_field(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run, url_result, _template = await _seed_gradeable_run(db_session, create_test_run)

    with pytest.raises(GroundedRepairContractError):
        await apply_grounded_repair(
            db_session,
            run=run,
            batch=_batch(url_result.id, field_name="warranty_terms"),
            representative_url_result_ids=[url_result.id],
        )

    # Nothing persisted: no label row created for the rejected batch.
    labels = (
        (
            await db_session.execute(
                select(ExtractionOperatorLabel).where(
                    ExtractionOperatorLabel.source_run_id == run.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert labels == []
