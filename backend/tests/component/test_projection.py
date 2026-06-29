"""Component tests for Knowledge Graph projection service (Slice 6).

Tests template fingerprinting, ExtractionResult projection, template skeleton
entities+relationships, extraction contracts (winner/rejected/rule), and claims.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawl.crud import create_crawl_run
from app.extraction.contracts import (
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionResult,
    RejectedEvidence,
    SourceLocator,
)
from app.extraction.surfaces import Surface
from app.models.knowledge_graph import (
    KGAssertionEvidence,
    KGClaim,
    KGEntity,
    KGExtractionContract,
    KGRelationship,
    KGSiteVersion,
)
from app.persistence.projection import (
    fingerprint_template,
    project_extraction_result,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fingerprint_stable_across_product_slug_changes() -> None:
    """Template fingerprint stable across product ID/slug changes (spec §5.1)."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(),
        collector_outcomes=(
            CollectorOutcome(
                collector_id="opengraph",
                outcome="produced_evidence",
                evidence_count=1,
            ),
        ),
        verdict="success",
    )

    fp1 = fingerprint_template(
        "https://example.com/products/widget-blue-123", "ecommerce_detail", result
    )
    fp2 = fingerprint_template(
        "https://example.com/products/widget-red-456", "ecommerce_detail", result
    )

    assert fp1 == fp2, "Equivalent PDPs should share template fingerprint"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fingerprint_differs_by_surface() -> None:
    """Template fingerprint changes when surface changes."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        collector_outcomes=(CollectorOutcome(collector_id="opengraph", outcome="ran"),),
        verdict="success",
    )

    fp_detail = fingerprint_template(
        "https://example.com/products", "ecommerce_detail", result
    )
    fp_listing = fingerprint_template(
        "https://example.com/products", "ecommerce_listing", result
    )

    assert fp_detail != fp_listing, (
        "Different surfaces must have different fingerprints"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_fingerprint_differs_by_route() -> None:
    """Template fingerprint changes when route pattern changes."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        collector_outcomes=(),
        verdict="success",
    )

    fp1 = fingerprint_template(
        "https://example.com/products/item", "ecommerce_detail", result
    )
    fp2 = fingerprint_template(
        "https://example.com/shop/item", "ecommerce_detail", result
    )

    assert fp1 != fp2, "Different routes must have different fingerprints"


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_template_skeleton_entities(
    db_session: AsyncSession,
) -> None:
    """Projection creates site, route, template, page entities."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        collector_outcomes=(),
        verdict="success",
    )

    counts = await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    assert counts["entities_upserted"] >= 4

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    by_type = {e.entity_type: e for e in entities}

    assert "site" in by_type
    assert by_type["site"].canonical_key == "example.com"

    assert "page_template" in by_type
    assert by_type["page_template"].properties["domain"] == "example.com"
    assert by_type["page_template"].properties["surface"] == "ecommerce_detail"

    site_version = (await db_session.execute(select(KGSiteVersion))).scalar_one()
    assert site_version.domain == "example.com"
    assert site_version.current_version == 2
    assert site_version.projection_status == "projected"
    assert site_version.last_projected_run_id is None

    assert "route_pattern" in by_type
    assert by_type["route_pattern"].properties["pattern"] == "/products/{id}"

    assert "page" in by_type
    assert by_type["page"].canonical_key == "https://example.com/products/widget"


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_template_skeleton_relationships(
    db_session: AsyncSession,
) -> None:
    """Projection creates SITE_HAS_TEMPLATE, TEMPLATE_MATCHES_ROUTE, PAGE_INSTANCE_OF_TEMPLATE."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        collector_outcomes=(),
        verdict="success",
    )

    counts = await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    assert counts["relationships_upserted"] >= 3

    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    rel_types = {r.relationship_type for r in rels}

    assert "SITE_HAS_TEMPLATE" in rel_types
    assert "TEMPLATE_MATCHES_ROUTE" in rel_types
    assert "PAGE_INSTANCE_OF_TEMPLATE" in rel_types


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_technology_entities_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Projection creates technology entities from collector outcomes."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        collector_outcomes=(
            CollectorOutcome(collector_id="jsonld", outcome="ran"),
            CollectorOutcome(collector_id="opengraph", outcome="ran"),
        ),
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    tech_entities = [e for e in entities if e.entity_type == "technology"]

    assert len(tech_entities) == 2
    tech_names = {e.properties["name"] for e in tech_entities}
    assert tech_names == {"jsonld", "opengraph"}

    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    tech_rels = [r for r in rels if r.relationship_type == "SITE_USES_TECHNOLOGY"]
    assert len(tech_rels) == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_product_entities_from_evidence(
    db_session: AsyncSession,
) -> None:
    """Projection creates product entities from Evidence with subject_scope."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(
            Evidence(
                evidence_id="e1",
                bundle_id="bundle-1",
                artifact_id="art1",
                collector_id="opengraph",
                collector_version="1.0",
                fact_type="product.title",
                raw_value="Widget Blue",
                value="Widget Blue",
                locator=SourceLocator(kind="css_selector", value="h1"),
                directness="direct",
                confidence=0.9,
                subject_id="prod-1",
                subject_scope="product",
            ),
        ),
        collector_outcomes=(),
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    products = [e for e in entities if e.entity_type == "product"]

    assert len(products) == 1
    assert products[0].canonical_key == "example.com:prod-1"

    # PAGE_MENTIONS_PRODUCT relationship
    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    mentions = [r for r in rels if r.relationship_type == "PAGE_MENTIONS_PRODUCT"]
    assert len(mentions) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_claims_from_evidence(
    db_session: AsyncSession,
    test_user,
) -> None:
    """Projection creates claims from Evidence."""
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    await db_session.flush()
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(
            Evidence(
                evidence_id="e1",
                bundle_id="bundle-1",
                artifact_id="art1",
                collector_id="opengraph",
                collector_version="1.0",
                fact_type="product.title",
                raw_value="Widget Blue",
                value="Widget Blue",
                locator=SourceLocator(kind="css_selector", value="h1"),
                directness="direct",
                confidence=0.9,
                subject_id="prod-1",
                subject_scope="product",
            ),
        ),
        collector_outcomes=(),
        verdict="success",
    )

    counts = await project_extraction_result(
        db_session,
        run_id=run.id,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    assert counts["claims_upserted"] == 1

    claims = (await db_session.execute(select(KGClaim))).scalars().all()
    assert len(claims) == 1
    assert claims[0].fact_type == "product.title"
    assert claims[0].value == {"raw": "Widget Blue", "processed": "Widget Blue"}
    assert claims[0].confidence == 0.9

    evidence = (await db_session.execute(select(KGAssertionEvidence))).scalars().all()
    assert len(evidence) == 1
    assert evidence[0].claim_id == claims[0].id
    assert evidence[0].source_run_id == run.id
    assert evidence[0].collector == "opengraph"

    site_version = (await db_session.execute(select(KGSiteVersion))).scalar_one()
    assert site_version.last_projected_run_id == run.id


@pytest.mark.asyncio
@pytest.mark.component
async def test_project_creates_extraction_contracts_from_decisions(
    db_session: AsyncSession,
) -> None:
    """Projection creates extraction contracts with winner/rejected/rule."""
    evidence_winner = Evidence(
        evidence_id="e1",
        bundle_id="bundle-1",
        artifact_id="art1",
        collector_id="opengraph",
        collector_version="1.0",
        fact_type="product.title",
        raw_value="Widget Blue",
        value="Widget Blue",
        locator=SourceLocator(kind="css_selector", value="h1"),
        directness="direct",
        confidence=0.95,
        subject_id="prod-1",
        subject_scope="product",
    )
    evidence_rejected = Evidence(
        evidence_id="e2",
        bundle_id="bundle-1",
        artifact_id="art1",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="product.title",
        raw_value="Widget",
        value="Widget",
        locator=SourceLocator(kind="json_pointer", value="/name"),
        directness="direct",
        confidence=0.7,
        subject_id="prod-1",
        subject_scope="product",
    )

    decision = Decision(
        decision_id="d1",
        entity_id="prod-1",
        fact_type="product.title",
        accepted_evidence_ids=("e1",),
        rejected=(RejectedEvidence(evidence_id="e2", reason="lower_confidence"),),
        finding_ids=(),
        rule_id="confidence_first",
        status="resolved",
    )

    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(evidence_winner, evidence_rejected),
        decisions=(decision,),
        collector_outcomes=(),
        verdict="success",
    )

    counts = await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    assert counts["contracts_upserted"] == 1

    contracts = (await db_session.execute(select(KGExtractionContract))).scalars().all()
    assert len(contracts) == 1

    contract = contracts[0]
    assert contract.surface == "ecommerce_detail"
    assert contract.canonical_field == "product.title"
    assert contract.resolver_rule == "confidence_first"
    assert contract.success_count == 1
    assert contract.rejection_count == 1
    assert "opengraph" in contract.selected_source

    # Candidates: winner + rejected
    assert len(contract.candidates) == 2
    assert contract.candidates[0]["rejected"] is False
    assert contract.candidates[1]["rejected"] is True
    assert contract.candidates[1]["reason"] == "lower_confidence"


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_idempotent_on_repeated_runs(
    db_session: AsyncSession,
) -> None:
    """Repeated projection of same result is idempotent."""
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(
            Evidence(
                evidence_id="e1",
                bundle_id="bundle-1",
                artifact_id="art1",
                collector_id="opengraph",
                collector_version="1.0",
                fact_type="product.title",
                raw_value="Widget",
                value="Widget",
                locator=SourceLocator(kind="css_selector", value="h1"),
                directness="direct",
                confidence=0.9,
                subject_id="prod-1",
                subject_scope="product",
            ),
        ),
        collector_outcomes=(),
        verdict="success",
    )

    counts_1 = await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    counts_2 = await project_extraction_result(
        db_session,
        run_id=2,
        url="https://example.com/products/widget",
        result=result,
    )
    await db_session.commit()

    # Second projection reuses template/product entities, updates page
    assert counts_1["entities_upserted"] >= 5
    assert counts_2["entities_upserted"] >= 5

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    templates = [e for e in entities if e.entity_type == "page_template"]
    products = [e for e in entities if e.entity_type == "product"]
    pages = [e for e in entities if e.entity_type == "page"]
    claims = (await db_session.execute(select(KGClaim))).scalars().all()
    rels = (await db_session.execute(select(KGRelationship))).scalars().all()

    # Template and product shared across runs
    assert len(templates) == 1
    assert len(products) == 1
    # Page entity reused (same URL)
    assert len(pages) == 1
    assert pages[0].properties["run_id"] == 2  # Updated to latest run
    assert len(claims) == 1
    assert (
        len([rel for rel in rels if rel.relationship_type == "PAGE_MENTIONS_PRODUCT"])
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_template_isolation_different_templates_separate_contracts(
    db_session: AsyncSession,
) -> None:
    """Different templates have separate extraction contracts."""
    result_detail = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        decisions=(
            Decision(
                decision_id="d1",
                entity_id="prod-1",
                fact_type="product.title",
                accepted_evidence_ids=("e1",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
        ),
        evidence=(
            Evidence(
                evidence_id="e1",
                bundle_id="bundle-1",
                artifact_id="art1",
                collector_id="opengraph",
                collector_version="1.0",
                fact_type="product.title",
                raw_value="Widget",
                value="Widget",
                locator=SourceLocator(kind="css_selector", value="h1"),
                directness="direct",
                confidence=0.9,
                subject_id="prod-1",
                subject_scope="product",
            ),
        ),
        collector_outcomes=(),
        verdict="success",
    )

    result_listing = ExtractionResult(
        surface=Surface.ECOMMERCE_LISTING,
        bundle_id="bundle-2",
        records=(),
        decisions=(
            Decision(
                decision_id="d2",
                entity_id="prod-2",
                fact_type="product.title",
                accepted_evidence_ids=("e2",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
        ),
        evidence=(
            Evidence(
                evidence_id="e2",
                bundle_id="bundle-2",
                artifact_id="art2",
                collector_id="jsonld",
                collector_version="1.0",
                fact_type="product.title",
                raw_value="Widget",
                value="Widget",
                locator=SourceLocator(kind="json_pointer", value="/name"),
                directness="direct",
                confidence=0.8,
                subject_id="prod-2",
                subject_scope="product",
            ),
        ),
        collector_outcomes=(),
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result_detail,
    )
    await db_session.commit()

    await project_extraction_result(
        db_session,
        run_id=2,
        url="https://example.com/products",
        result=result_listing,
    )
    await db_session.commit()

    contracts = (await db_session.execute(select(KGExtractionContract))).scalars().all()
    assert len(contracts) == 2

    detail_contract = [c for c in contracts if c.surface == "ecommerce_detail"][0]
    listing_contract = [c for c in contracts if c.surface == "ecommerce_listing"][0]

    assert "opengraph" in detail_contract.selected_source
    assert "jsonld" in listing_contract.selected_source
