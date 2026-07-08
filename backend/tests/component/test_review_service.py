from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.crawl_run import CrawlRecord, CrawlUrlResult
from app.models.extraction_memory import (
    ExtractionManifest,
    ExtractionOperatorLabel,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.crawl.review import (
    list_domain_field_feedback,
    save_grounded_correction,
    save_review,
)
from app.evaluation.grounded_corrections import GroundedCorrectionScopeMismatch
from app.core.records.schema_service import ResolvedSchema
from app.core.records.schema_service import load_resolved_schema
from app.persistence.artifacts import ArtifactRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

DomainFieldFeedback = ExtractionOperatorLabel
ReviewPromotion = ExtractionOperatorLabel


@pytest.mark.asyncio
@pytest.mark.component
async def test_save_review_persists_mapping_and_promotes_values(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget Prime"},
        raw_data={},
        discovered_data={
            "review_bucket": [
                {
                    "key": "material_notes",
                    "value": "Cotton blend",
                    "source": "dom",
                }
            ]
        },
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    result = await save_review(
        db_session,
        run,
        [
            {
                "source_field": "material_notes",
                "output_field": "materials",
                "selected": True,
            }
        ],
    )

    await db_session.refresh(record)
    promotion = (
        await db_session.execute(
            select(ReviewPromotion)
            .where(ReviewPromotion.source_run_id == run.id)
            .order_by(ReviewPromotion.id.desc())
            .limit(1)
        )
    ).scalar_one()

    assert result["field_mapping"] == {"material_notes": "materials"}
    assert "materials" in result["canonical_fields"]
    assert record.data["materials"] == "Cotton blend"
    assert record.discovered_data["review_bucket"][0]["key"] == "material_notes"
    assert promotion.field_mapping == {"material_notes": "materials"}
    assert promotion.approved_schema["fields"] == result["canonical_fields"]
    assert promotion.approved_schema["saved_at"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_resolved_schema_reads_latest_review_promotion_snapshot(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    db_session.add_all(
        [
            ReviewPromotion(
                label_kind="review_promotion",
                source_run_id=run.id,
                domain="example.com",
                surface="ecommerce_detail",
                approved_schema={
                    "fields": ["title", "materials"],
                    "baseline_fields": ["title"],
                    "new_fields": ["materials"],
                    "deprecated_fields": [],
                    "source": "review",
                    "saved_at": "2026-04-10T12:00:00+00:00",
                },
                field_mapping={"material_notes": "materials"},
            ),
            ReviewPromotion(
                label_kind="review_promotion",
                source_run_id=run.id,
                domain="example.com",
                surface="ecommerce_detail",
                approved_schema={
                    "fields": ["title", "materials", "care"],
                    "baseline_fields": ["title"],
                    "new_fields": ["materials", "care"],
                    "deprecated_fields": [],
                    "source": "review",
                    "saved_at": "2026-04-11T12:00:00+00:00",
                },
                field_mapping={
                    "material_notes": "materials",
                    "care_instructions": "care",
                },
            ),
        ]
    )
    await db_session.commit()

    schema = await load_resolved_schema(
        db_session,
        "ecommerce_detail",
        "https://example.com/products/widget",
        explicit_fields=["materials", "dimensions"],
    )

    assert schema.domain == "example.com"
    assert schema.source == "review"
    assert schema.saved_at == "2026-04-11T12:00:00+00:00"
    assert "title" in schema.fields
    assert "materials" in schema.fields
    assert "care" in schema.fields
    assert "dimensions" in schema.fields


@pytest.mark.asyncio
@pytest.mark.component
async def test_save_review_excludes_falsy_normalized_new_fields(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={},
        raw_data={},
        discovered_data={
            "review_bucket": [
                {
                    "key": "material_notes",
                    "value": "Cotton blend",
                    "source": "dom",
                }
            ]
        },
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()

    async def _fake_load_resolved_schema(*args, **kwargs) -> ResolvedSchema:
        del args, kwargs
        return ResolvedSchema(
            surface="ecommerce_detail",
            domain="example.com",
            baseline_fields=["title"],
            fields=["title"],
            new_fields=[],
            deprecated_fields=[],
            source="baseline",
            saved_at=None,
            stale=False,
        )

    call_counts: dict[str, int] = {}

    def _fake_normalize_review_target(surface: str, value: object) -> str:
        del surface
        text = str(value or "").strip().lower()
        call_counts[text] = call_counts.get(text, 0) + 1
        if text == "materials" and call_counts[text] == 1:
            return "materials"
        if text == "materials":
            return ""
        return text

    monkeypatch.setattr(
        "app.crawl.review.load_resolved_schema", _fake_load_resolved_schema
    )
    monkeypatch.setattr(
        "app.crawl.review.normalize_review_target",
        _fake_normalize_review_target,
    )

    result = await save_review(
        db_session,
        run,
        [
            {
                "source_field": "material_notes",
                "output_field": "materials",
                "selected": True,
            }
        ],
    )

    promotion = (
        await db_session.execute(
            select(ReviewPromotion)
            .where(ReviewPromotion.source_run_id == run.id)
            .order_by(ReviewPromotion.id.desc())
            .limit(1)
        )
    ).scalar_one()

    assert result["field_mapping"] == {"material_notes": "materials"}
    assert promotion.approved_schema["new_fields"] == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_domain_field_feedback_skips_invalid_serialized_source_record_ids(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    db_session.add(
        DomainFieldFeedback(
            label_kind="field_feedback",
            domain="example.com",
            surface="ecommerce_detail",
            field_name="price",
            action="reject",
            source_kind="selector",
            source_value=".price",
            source_run_id=run.id,
            payload={
                "source_record_ids": ["7", "oops", -2, "", None],
            },
        )
    )
    await db_session.commit()

    rows = await list_domain_field_feedback(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert rows[0]["source_record_ids"] == [7, -2]


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_correction_rejects_text_only_field_label(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    with pytest.raises(ValueError, match="Every label requires a grounding reference"):
        await save_grounded_correction(
            db_session,
            run=run,
            labels=[
                {
                    "target_kind": "field",
                    "subject_id": "product:1",
                    "field_name": "price",
                    "canonical_value": "19.99",
                    "semantic_role": "primary_price",
                    "locale_interpretation": "USD",
                    "grounding": [],
                }
            ],
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_correction_requires_representative_replay_before_activation(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    result = await save_grounded_correction(
        db_session,
        run=run,
        activate=True,
        labels=[
            {
                "target_kind": "field",
                "subject_id": "product:1",
                "field_name": "price",
                "canonical_value": "19.99",
                "semantic_role": "primary_price",
                "locale_interpretation": "USD",
                "grounding": [
                    {
                        "kind": "node",
                        "artifact_id": "url-result:1:html",
                        "locator": "css:.price",
                    }
                ],
            }
        ],
        representative_url_result_ids=[],
    )

    label = (
        await db_session.execute(
            select(ExtractionOperatorLabel)
            .where(ExtractionOperatorLabel.id == result["correction_id"])
            .limit(1)
        )
    ).scalar_one()

    assert result["activation_status"] == "replay_failed"
    assert result["replay"]["passed"] is False
    assert label.payload["activation_requested"] is True
    assert label.payload["activation_status"] == "replay_failed"


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_correction_proposal_keeps_all_field_selectors_and_metadata(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    result = await save_grounded_correction(
        db_session,
        run=run,
        labels=[
            {
                "target_kind": "field",
                "subject_id": "product:1",
                "field_name": "price",
                "canonical_value": "19.99",
                "semantic_role": "primary_price",
                "locale_interpretation": "USD",
                "grounding": [
                    {
                        "kind": "node",
                        "artifact_id": "url-result:1:html",
                        "locator": "css:.sale-price",
                    }
                ],
            },
            {
                "target_kind": "field",
                "subject_id": "product:1",
                "field_name": "price",
                "canonical_value": "19.99",
                "semantic_role": "display_price",
                "locale_interpretation": "en-US",
                "grounding": [
                    {
                        "kind": "node",
                        "artifact_id": "url-result:1:html",
                        "locator": "css:[itemprop='price']",
                    }
                ],
            },
        ],
        representative_url_result_ids=[],
    )

    label = await db_session.get(ExtractionOperatorLabel, result["correction_id"])
    assert label is not None
    rules = sorted(
        label.payload["proposal"]["selector_rules"],
        key=lambda row: row["css_selector"],
    )
    assert [
        (row["css_selector"], row["semantic_role"], row["locale_interpretation"])
        for row in rules
    ] == [
        (".sale-price", "primary_price", "USD"),
        ("[itemprop='price']", "display_price", "en-US"),
    ]
    assert label.payload["proposal"]["conflicts"] == [
        {
            "field_name": "price",
            "selectors": [".sale-price", "[itemprop='price']"],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_correction_replays_and_activates_immutable_release(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
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

    result = await save_grounded_correction(
        db_session,
        run=run,
        activate=True,
        labels=[
            {
                "target_kind": "field",
                "subject_id": "product:1",
                "field_name": "price",
                "canonical_value": "19.99",
                "semantic_role": "primary_price",
                "locale_interpretation": "USD",
                "grounding": [
                    {
                        "kind": "node",
                        "artifact_id": f"url-result:{url_result.id}:page.html",
                        "locator": "css:.price",
                    }
                ],
            }
        ],
        representative_url_result_ids=[url_result.id],
    )

    await db_session.refresh(run)
    label = await db_session.get(ExtractionOperatorLabel, result["correction_id"])
    recipe = (
        await db_session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.kind == "selectors",
            )
        )
    ).scalar_one()
    release = (
        await db_session.execute(
            select(ExtractionReleaseSnapshot).where(
                ExtractionReleaseSnapshot.run_id == run.id
            )
        )
    ).scalar_one()

    assert result["activation_status"] == "activated"
    assert result["replay"]["passed"] is True
    assert result["replay"]["template_id"] == str(template.id)
    assert label is not None
    assert label.template_id == template.id
    assert label.payload["labels"][0]["authority"] == "human_verified"
    assert recipe.payload["rules"][0]["field_name"] == "price"
    assert recipe.payload["rules"][0]["css_selector"] == ".price"
    assert run.extraction_release_snapshot_id == release.id
    # ecommerce_detail is a "proven" surface: extraction is deterministic via
    # source-pins, so css selector recipes are intentionally compiled away at
    # release time (see test_release_payload_strips_commerce_detail_selector_recipes
    # and the runtime short-circuit in record_extraction_stage._load_selector_rules,
    # which returns [] for this surface). The human correction is durably stored as
    # a recipe (asserted above) but is absent from the frozen release for detail.
    assert release.payload["templates"][0]["selector_rules"] == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_grounded_correction_activation_rejects_template_scope_mismatch(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
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
        domain="other.example.com",
        surface=run.surface,
        fingerprint="wrong-domain-template-v1",
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

    with pytest.raises(GroundedCorrectionScopeMismatch):
        await save_grounded_correction(
            db_session,
            run=run,
            activate=True,
            labels=[
                {
                    "target_kind": "field",
                    "subject_id": "product:1",
                    "field_name": "price",
                    "canonical_value": "19.99",
                    "semantic_role": "primary_price",
                    "locale_interpretation": "USD",
                    "grounding": [
                        {
                            "kind": "node",
                            "artifact_id": f"url-result:{url_result.id}:page.html",
                            "locator": "css:.price",
                        }
                    ],
                }
            ],
            representative_url_result_ids=[url_result.id],
        )
