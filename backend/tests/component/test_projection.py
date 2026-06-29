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
    CommerceDetailRecord,
    CommerceVariantRecord,
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
        locator=SourceLocator(kind="json_pointer", value="/items/0/name"),
        directness="direct",
        confidence=0.7,
        subject_id="prod-1",
        subject_scope="product",
    )
    evidence_rejected_duplicate = evidence_rejected.model_copy(
        update={
            "evidence_id": "e3",
            "locator": SourceLocator(kind="json_pointer", value="/items/1/name"),
        }
    )

    decision = Decision(
        decision_id="d1",
        entity_id="prod-1",
        fact_type="product.title",
        accepted_evidence_ids=("e1",),
        rejected=(
            RejectedEvidence(evidence_id="e2", reason="lower_confidence"),
            RejectedEvidence(evidence_id="e3", reason="lower_confidence"),
        ),
        finding_ids=(),
        rule_id="confidence_first",
        status="resolved",
    )

    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(evidence_winner, evidence_rejected, evidence_rejected_duplicate),
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
    assert "opengraph" in contract.selected_source

    # Candidates are source patterns, not duplicate observations.
    assert len(contract.candidates) == 2
    assert contract.candidates[0]["rejected"] is False
    assert contract.candidates[0]["value_preview"] == "Widget Blue"
    assert contract.candidates[1]["rejected"] is True
    assert contract.candidates[1]["reason"] == "lower_confidence"
    assert contract.candidates[1]["value_preview"] == "Widget"
    assert contract.rejection_count == 1


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


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_creates_canonical_relationships_from_resolved_decisions(
    db_session: AsyncSession,
) -> None:
    brand_ev = Evidence(
        evidence_id="brand-1",
        bundle_id="bundle-1",
        artifact_id="art1",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="product.brand",
        raw_value="ACME",
        value="ACME",
        locator=SourceLocator(kind="json_pointer", value="/brand/name"),
        directness="direct",
        confidence=0.95,
        subject_id="prod-1",
        subject_scope="product",
    )
    seller_ev = Evidence(
        evidence_id="seller-1",
        bundle_id="bundle-1",
        artifact_id="art1",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="offer.seller",
        raw_value="ACME Store",
        value="ACME Store",
        locator=SourceLocator(kind="json_pointer", value="/offers/seller/name"),
        directness="direct",
        confidence=0.9,
        subject_id="offer-1",
        parent_subject_id="prod-1",
        subject_scope="offer",
    )
    price_ev = Evidence(
        evidence_id="price-1",
        bundle_id="bundle-1",
        artifact_id="art1",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="offer.price",
        raw_value="99.00",
        value=99.0,
        locator=SourceLocator(kind="json_pointer", value="/offers/price"),
        directness="direct",
        confidence=0.95,
        subject_id="offer-1",
        parent_subject_id="prod-1",
        subject_scope="offer",
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle-1",
        records=(),
        evidence=(brand_ev, seller_ev, price_ev),
        decisions=(
            Decision(
                decision_id="d-brand",
                entity_id="prod-1",
                fact_type="product.brand",
                accepted_evidence_ids=("brand-1",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
            Decision(
                decision_id="d-seller",
                entity_id="offer-1",
                fact_type="offer.seller",
                accepted_evidence_ids=("seller-1",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
            Decision(
                decision_id="d-price",
                entity_id="offer-1",
                fact_type="offer.price",
                accepted_evidence_ids=("price-1",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
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
    assert {entity.entity_type for entity in entities} >= {
        "product",
        "brand",
        "offer",
        "seller",
    }
    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    rel_types = {rel.relationship_type for rel in rels}
    assert "PRODUCT_MADE_BY" in rel_types
    assert "PRODUCT_HAS_OFFER" in rel_types
    assert "OFFER_SOLD_BY" in rel_types
    assert sum(rel.relationship_type == "PRODUCT_HAS_OFFER" for rel in rels) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_repeats_until_deferred_canonical_relationships_resolve(
    db_session: AsyncSession,
) -> None:
    evidence = Evidence(
        evidence_id="deferred-brand",
        bundle_id="bundle",
        artifact_id="artifact",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="product.brand",
        raw_value="ACME",
        value="ACME",
        locator=SourceLocator(kind="json_pointer", value="/brand"),
        directness="direct",
        confidence=0.9,
        subject_id="page-1",
        subject_scope="unknown",
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle",
        records=(),
        evidence=(evidence,),
        decisions=(
            Decision(
                decision_id="deferred-brand-decision",
                entity_id="product:prod-deferred",
                fact_type="product.brand",
                accepted_evidence_ids=(evidence.evidence_id,),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
        ),
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/deferred",
        result=result,
    )
    await db_session.commit()

    relationship_types = set(
        (await db_session.execute(select(KGRelationship.relationship_type))).scalars()
    )
    assert "PRODUCT_MADE_BY" in relationship_types


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_excludes_unrelated_resolved_decisions_from_product_claims(
    db_session: AsyncSession,
) -> None:
    evidence = Evidence(
        evidence_id="page-meta",
        bundle_id="bundle",
        artifact_id="artifact",
        collector_id="opengraph",
        collector_version="1.0",
        fact_type="page.meta_description",
        raw_value="Page metadata",
        value="Page metadata",
        locator=SourceLocator(kind="css_selector", value="meta[name='description']"),
        directness="direct",
        confidence=0.9,
        subject_id="page-1",
        subject_scope="document",
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle",
        records=(),
        evidence=(evidence,),
        decisions=(
            Decision(
                decision_id="page-meta-decision",
                entity_id="product:prod-1",
                fact_type=evidence.fact_type,
                accepted_evidence_ids=(evidence.evidence_id,),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
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

    unrelated_claims = (
        (
            await db_session.execute(
                select(KGClaim).where(KGClaim.fact_type == "page.meta_description")
            )
        )
        .scalars()
        .all()
    )
    assert unrelated_claims == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_creates_same_as_only_for_deterministic_gtin(
    db_session: AsyncSession,
) -> None:
    def _result(product_id: str, title: str, gtin: str | None) -> ExtractionResult:
        evidence = [
            Evidence(
                evidence_id=f"title-{product_id}",
                bundle_id="bundle",
                artifact_id="art",
                collector_id="jsonld",
                collector_version="1.0",
                fact_type="product.title",
                raw_value=title,
                value=title,
                locator=SourceLocator(kind="json_pointer", value="/name"),
                directness="direct",
                confidence=0.9,
                subject_id=product_id,
                subject_scope="product",
            )
        ]
        decisions = [
            Decision(
                decision_id=f"d-title-{product_id}",
                entity_id=product_id,
                fact_type="product.title",
                accepted_evidence_ids=(f"title-{product_id}",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            )
        ]
        if gtin:
            evidence.append(
                Evidence(
                    evidence_id=f"gtin-{product_id}",
                    bundle_id="bundle",
                    artifact_id="art",
                    collector_id="jsonld",
                    collector_version="1.0",
                    fact_type="product.gtin",
                    raw_value=gtin,
                    value=gtin,
                    locator=SourceLocator(kind="json_pointer", value="/gtin"),
                    directness="direct",
                    confidence=0.98,
                    subject_id=product_id,
                    subject_scope="product",
                )
            )
            decisions.append(
                Decision(
                    decision_id=f"d-gtin-{product_id}",
                    entity_id=product_id,
                    fact_type="product.gtin",
                    accepted_evidence_ids=(f"gtin-{product_id}",),
                    rejected=(),
                    finding_ids=(),
                    rule_id="first_available",
                    status="resolved",
                )
            )
        return ExtractionResult(
            surface=Surface.ECOMMERCE_DETAIL,
            bundle_id="bundle",
            records=(),
            evidence=tuple(evidence),
            decisions=tuple(decisions),
            verdict="success",
        )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://site-a.example/products/widget",
        result=_result("a", "Shared Widget", "00012345678905"),
    )
    await project_extraction_result(
        db_session,
        run_id=2,
        url="https://site-b.example/products/widget",
        result=_result("b", "Shared Widget", "0001 2345-678905"),
    )
    await project_extraction_result(
        db_session,
        run_id=3,
        url="https://site-c.example/products/widget",
        result=_result("c", "Shared Widget", None),
    )
    await db_session.commit()

    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    same_as = [rel for rel in rels if rel.relationship_type == "PRODUCT_SAME_AS"]
    assert len(same_as) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_stores_variants_as_aggregate_claim_only(
    db_session: AsyncSession,
) -> None:
    evidence = Evidence(
        evidence_id="title-1",
        bundle_id="bundle",
        artifact_id="art",
        collector_id="jsonld",
        collector_version="1.0",
        fact_type="product.title",
        raw_value="Variant Widget",
        value="Variant Widget",
        locator=SourceLocator(kind="json_pointer", value="/name"),
        directness="direct",
        confidence=0.9,
        subject_id="prod-1",
        subject_scope="product",
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle",
        records=(
            CommerceDetailRecord(
                url="https://example.com/products/widget",
                title="Variant Widget",
                variants=(
                    CommerceVariantRecord(
                        variant_id="red-s",
                        sku="RS",
                        color="Red",
                        size="S",
                    ),
                    CommerceVariantRecord(
                        variant_id="blue-m",
                        sku="BM",
                        color="Blue",
                        size="M",
                    ),
                ),
            ),
        ),
        evidence=(evidence,),
        decisions=(
            Decision(
                decision_id="d-title",
                entity_id="prod-1",
                fact_type="product.title",
                accepted_evidence_ids=("title-1",),
                rejected=(),
                finding_ids=(),
                rule_id="first_available",
                status="resolved",
            ),
        ),
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/widget",
        result=result,
    )
    record = result.records[0]
    reversed_result = result.model_copy(
        update={
            "records": (
                record.model_copy(
                    update={"variants": tuple(reversed(record.variants))}
                ),
            )
        }
    )
    await project_extraction_result(
        db_session,
        run_id=2,
        url="https://example.com/products/widget",
        result=reversed_result,
    )
    await db_session.commit()

    variant_entities = (
        (
            await db_session.execute(
                select(KGEntity).where(KGEntity.entity_type == "variant")
            )
        )
        .scalars()
        .all()
    )
    assert variant_entities == []
    claim = (
        await db_session.execute(
            select(KGClaim).where(KGClaim.fact_type == "product.variant_set")
        )
    ).scalar_one()
    assert claim.value["count"] == 2
    assert claim.value["axes"] == ["color", "size"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_projection_skips_variant_set_for_multi_product_result(
    db_session: AsyncSession,
) -> None:
    evidence = tuple(
        Evidence(
            evidence_id=f"title-{product_id}",
            bundle_id="bundle",
            artifact_id="artifact",
            collector_id="jsonld",
            collector_version="1.0",
            fact_type="product.title",
            raw_value=title,
            value=title,
            locator=SourceLocator(kind="json_pointer", value="/name"),
            directness="direct",
            confidence=0.9,
            subject_id=product_id,
            subject_scope="product",
        )
        for product_id, title in (("prod-1", "One"), ("prod-2", "Two"))
    )
    decisions = tuple(
        Decision(
            decision_id=f"decision-{row.subject_id}",
            entity_id=row.subject_id,
            fact_type=row.fact_type,
            accepted_evidence_ids=(row.evidence_id,),
            rejected=(),
            finding_ids=(),
            rule_id="first_available",
            status="resolved",
        )
        for row in evidence
    )
    result = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        bundle_id="bundle",
        records=(
            CommerceDetailRecord(
                url="https://example.com/products/mixed",
                title="Mixed",
                variants=(CommerceVariantRecord(variant_id="red", color="Red"),),
            ),
        ),
        evidence=evidence,
        decisions=decisions,
        verdict="success",
    )

    await project_extraction_result(
        db_session,
        run_id=1,
        url="https://example.com/products/mixed",
        result=result,
    )
    await db_session.commit()

    variant_claims = (
        (
            await db_session.execute(
                select(KGClaim).where(KGClaim.fact_type == "product.variant_set")
            )
        )
        .scalars()
        .all()
    )
    assert variant_claims == []
