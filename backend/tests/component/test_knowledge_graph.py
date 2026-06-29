"""Knowledge Graph repository and reset-separation tests (Slice 5).

Validates transactional batch upserts, per-site locking, bounded neighbourhood
reads, explicit purge, and reset-separation: the graph is preserved across
crawl, Domain Memory, and application resets but is removed only by an explicit
graph purge (feature spec §8).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawl.crud import create_crawl_run
from app.crawl.dashboard_service import (
    reset_application_data,
    reset_crawl_data,
    reset_domain_memory,
    reset_knowledge_graph,
)
from app.models.crawl_run import CrawlRun
from app.models.domain_memory import DomainMemory
from app.models.knowledge_graph import (
    KGAssertionEvidence,
    KGClaim,
    KGEntity,
    KGExtractionContract,
    KGRelationship,
    KGSiteVersion,
)
from app.persistence.knowledge_graph import (
    ClaimInput,
    ContractInput,
    EntityInput,
    RelationshipInput,
    add_evidence,
    compute_value_hash,
    count_graph_rows,
    fetch_neighborhood,
    lock_site_version,
    purge_graph,
    upsert_claims,
    upsert_contracts,
    upsert_entities,
    upsert_relationships,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_lock_site_version_creates_and_serializes(
    db_session: AsyncSession,
) -> None:
    """lock_site_version creates a new site-version under a row lock."""
    site = await lock_site_version(db_session, "example.com")
    assert site.domain == "example.com"
    assert site.current_version == 1
    assert site.projection_status == "pending"


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_entities_idempotent_on_natural_key(
    db_session: AsyncSession,
) -> None:
    """Entities upsert on (entity_type, canonical_key); repeat is no-op."""
    entity_inputs = [
        EntityInput(
            entity_type="product",
            canonical_key="widget-blue",
            canonical_name="Widget Blue",
            properties={"color": "blue"},
        ),
    ]
    ids_1 = await upsert_entities(db_session, entity_inputs)
    await db_session.commit()
    assert len(ids_1) == 1
    original_id = ids_1[("product", "widget-blue")]

    # Upsert with different name/properties.
    entity_inputs_2 = [
        EntityInput(
            entity_type="product",
            canonical_key="widget-blue",
            canonical_name="Widget Blue v2",
            properties={"color": "navy"},
        ),
    ]
    ids_2 = await upsert_entities(db_session, entity_inputs_2)
    await db_session.commit()
    assert ids_2[("product", "widget-blue")] == original_id

    entity = (
        await db_session.execute(select(KGEntity).where(KGEntity.id == original_id))
    ).scalar_one()
    assert entity.canonical_name == "Widget Blue v2"
    assert entity.properties == {"color": "navy"}


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_relationships_idempotent_on_triple(
    db_session: AsyncSession,
) -> None:
    """Relationships upsert on (source, target, type)."""
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    db_session.add_all(
        [
            KGEntity(
                id=source_id,
                entity_type="product",
                canonical_key="widget",
                canonical_name="Widget",
            ),
            KGEntity(
                id=target_id,
                entity_type="brand",
                canonical_key="acme",
                canonical_name="ACME",
            ),
        ]
    )
    await db_session.commit()

    rel_inputs = [
        RelationshipInput(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relationship_type="PRODUCT_MADE_BY",
            confidence=0.9,
        ),
    ]
    count_1 = await upsert_relationships(db_session, rel_inputs)
    await db_session.commit()
    assert count_1 == 1

    # Re-upsert updates confidence.
    rel_inputs_2 = [
        RelationshipInput(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relationship_type="PRODUCT_MADE_BY",
            confidence=1.0,
        ),
    ]
    count_2 = await upsert_relationships(db_session, rel_inputs_2)
    await db_session.commit()
    assert count_2 == 1

    rels = (await db_session.execute(select(KGRelationship))).scalars().all()
    assert len(rels) == 1
    assert rels[0].confidence == 1.0


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_relationships_deduplicates_triples_within_one_batch(
    db_session: AsyncSession,
) -> None:
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    db_session.add_all(
        [
            KGEntity(
                id=source_id,
                entity_type="product",
                canonical_key="duplicate-edge-product",
            ),
            KGEntity(
                id=target_id,
                entity_type="offer",
                canonical_key="duplicate-edge-offer",
            ),
        ]
    )
    await db_session.flush()
    relationships = [
        RelationshipInput(
            source_entity_id=source_id,
            target_entity_id=target_id,
            relationship_type="PRODUCT_HAS_OFFER",
            properties={"field": field},
        )
        for field in ("offer.price", "offer.currency", "offer.availability")
    ]

    count = await upsert_relationships(db_session, relationships)
    await db_session.commit()

    assert count == 1
    saved = (await db_session.execute(select(KGRelationship))).scalar_one()
    assert saved.relationship_type == "PRODUCT_HAS_OFFER"


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_claims_and_compute_value_hash(
    db_session: AsyncSession,
) -> None:
    """Claims upsert on (entity_id, fact_type, value_hash)."""
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    claim_inputs = [
        ClaimInput(
            entity_id=entity_id,
            fact_type="price",
            value={"amount": 19.99, "currency": "USD"},
            confidence=0.95,
        ),
    ]
    ids = await upsert_claims(db_session, [*claim_inputs, *claim_inputs])
    await db_session.commit()
    assert len(ids) == 1

    claim = (
        await db_session.execute(select(KGClaim).where(KGClaim.id == ids[0]))
    ).scalar_one()
    assert claim.value == {"amount": 19.99, "currency": "USD"}
    expected_hash = compute_value_hash({"amount": 19.99, "currency": "USD"})
    assert claim.value_hash == expected_hash

    # Re-upsert identical value is idempotent.
    ids_2 = await upsert_claims(db_session, claim_inputs)
    await db_session.commit()
    assert ids_2 == ids


@pytest.mark.asyncio
@pytest.mark.component
async def test_add_evidence_to_claim_with_nullable_run(
    db_session: AsyncSession,
    test_user,
) -> None:
    """Evidence can reference a crawl run via SET NULL FK."""
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/widget",
            "surface": "ecommerce_detail",
        },
    )
    await db_session.commit()

    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    claim_inputs = [
        ClaimInput(
            entity_id=entity_id,
            fact_type="title",
            value={"text": "Widget"},
        ),
    ]
    claim_ids = await upsert_claims(db_session, claim_inputs)
    await db_session.commit()

    evidence = await add_evidence(
        db_session,
        claim_id=claim_ids[0],
        source_run_id=run.id,
        collector="opengraph",
        locator="og:title",
        value_preview="Widget",
        confidence=0.9,
    )
    await db_session.commit()
    assert evidence.source_run_id == run.id

    # Delete the run; evidence.source_run_id becomes NULL.
    await db_session.delete(run)
    await db_session.commit()

    await db_session.refresh(evidence)
    assert evidence.source_run_id is None
    assert evidence.collector == "opengraph"


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_contracts_idempotent_on_scope(
    db_session: AsyncSession,
) -> None:
    """Contracts upsert on (template_id, surface, canonical_field)."""
    template_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=template_id,
            entity_type="page_template",
            canonical_key="ecommerce-detail-v1",
            canonical_name="Ecommerce Detail",
        )
    )
    await db_session.commit()

    contract_inputs = [
        ContractInput(
            template_id=template_id,
            surface="ecommerce_detail",
            canonical_field="price",
            candidates=[{"source": "json_ld", "priority": 1}],
            success_count=5,
        ),
    ]
    count_1 = await upsert_contracts(db_session, contract_inputs)
    await db_session.commit()
    assert count_1 == 1

    # Re-upsert updates counters.
    contract_inputs_2 = [
        ContractInput(
            template_id=template_id,
            surface="ecommerce_detail",
            canonical_field="price",
            candidates=[{"source": "json_ld", "priority": 1}],
            success_count=10,
        ),
    ]
    count_2 = await upsert_contracts(db_session, contract_inputs_2)
    await db_session.commit()
    assert count_2 == 1

    contracts = (await db_session.execute(select(KGExtractionContract))).scalars().all()
    assert len(contracts) == 1
    assert contracts[0].success_count == 10


@pytest.mark.asyncio
@pytest.mark.component
async def test_upsert_contracts_preserves_history_when_promoted_to_operator(
    db_session: AsyncSession,
) -> None:
    template_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=template_id,
            entity_type="page_template",
            canonical_key="operator-promotion-template",
            canonical_name="Operator promotion",
        )
    )
    await db_session.flush()
    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.brand",
                selected_source="jsonld:/brand",
                selection_origin="generic",
            )
        ],
    )
    history = ({"selected_source": "css_recipe:.brand"},)
    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.brand",
                selected_source="css_recipe:.brand",
                selection_origin="operator",
                selection_history=history,
            )
        ],
    )
    await db_session.commit()

    contract = (await db_session.execute(select(KGExtractionContract))).scalar_one()
    assert contract.selected_source == "css_recipe:.brand"
    assert contract.selection_origin == "operator"
    assert contract.selection_history == list(history)

    second_history = ({"selected_source": "css_recipe:.product-brand"},)
    await upsert_contracts(
        db_session,
        [
            ContractInput(
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.brand",
                selected_source="css_recipe:.product-brand",
                selection_origin="operator",
                selection_history=second_history,
            )
        ],
    )
    await db_session.commit()
    await db_session.refresh(contract)
    assert contract.selected_source == "css_recipe:.product-brand"
    assert contract.selection_history == [*history, *second_history]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_neighborhood_bounded_recursive_cte(
    db_session: AsyncSession,
) -> None:
    """fetch_neighborhood returns entities within depth hops, bounded."""
    product_id = uuid.uuid4()
    brand_id = uuid.uuid4()
    category_id = uuid.uuid4()
    db_session.add_all(
        [
            KGEntity(
                id=product_id,
                entity_type="product",
                canonical_key="widget",
                canonical_name="Widget",
            ),
            KGEntity(
                id=brand_id,
                entity_type="brand",
                canonical_key="acme",
                canonical_name="ACME",
            ),
            KGEntity(
                id=category_id,
                entity_type="category",
                canonical_key="tools",
                canonical_name="Tools",
            ),
        ]
    )
    await db_session.commit()

    await upsert_relationships(
        db_session,
        [
            RelationshipInput(
                source_entity_id=product_id,
                target_entity_id=brand_id,
                relationship_type="PRODUCT_MADE_BY",
            ),
            RelationshipInput(
                source_entity_id=product_id,
                target_entity_id=category_id,
                relationship_type="PRODUCT_IN_CATEGORY",
            ),
        ],
    )
    await db_session.commit()

    neighbors = await fetch_neighborhood(db_session, product_id, depth=1)
    assert set(neighbors) == {product_id, brand_id, category_id}


@pytest.mark.asyncio
@pytest.mark.component
async def test_count_graph_rows(db_session: AsyncSession) -> None:
    """count_graph_rows returns per-table counts."""
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    counts = await count_graph_rows(db_session)
    assert counts["kg_entities"] == 1
    assert counts["kg_site_versions"] == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_purge_graph_removes_all_kg_tables(
    db_session: AsyncSession,
) -> None:
    """purge_graph deletes every KG row in child-before-parent order."""
    entity_id = uuid.uuid4()
    template_id = uuid.uuid4()
    relationship_id = uuid.uuid4()
    claim_id = uuid.uuid4()
    db_session.add_all(
        [
            KGEntity(
                id=entity_id,
                entity_type="product",
                canonical_key="widget",
                canonical_name="Widget",
            ),
            KGEntity(
                id=template_id,
                entity_type="page_template",
                canonical_key="example.com:ecommerce_detail:template",
                canonical_name="Template",
            ),
            KGSiteVersion(domain="example.com"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            KGRelationship(
                id=relationship_id,
                source_entity_id=template_id,
                target_entity_id=entity_id,
                relationship_type="PAGE_MENTIONS_PRODUCT",
            ),
            KGClaim(
                id=claim_id,
                entity_id=entity_id,
                fact_type="product.title",
                value={"raw": "Widget", "processed": "Widget"},
                value_hash=compute_value_hash({"raw": "Widget", "processed": "Widget"}),
            ),
            KGExtractionContract(
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.title",
            ),
        ]
    )
    await db_session.flush()
    db_session.add(
        KGAssertionEvidence(
            claim_id=claim_id,
            source_run_id=None,
            collector="opengraph",
            locator="og:title",
            value_preview="Widget",
        )
    )
    await db_session.commit()

    counts_before = await count_graph_rows(db_session)
    assert all(value > 0 for value in counts_before.values())

    deleted = await purge_graph(db_session)
    await db_session.commit()
    assert all(value > 0 for value in deleted.values())

    counts_after = await count_graph_rows(db_session)
    assert all(value == 0 for value in counts_after.values())


@pytest.mark.asyncio
@pytest.mark.component
async def test_reset_crawl_data_preserves_knowledge_graph(
    db_session: AsyncSession,
    test_user,
) -> None:
    """reset_crawl_data wipes crawl tables but leaves the graph intact."""
    await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/widget",
            "surface": "ecommerce_detail",
        },
    )
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    reset_result = await reset_crawl_data(db_session)
    await db_session.commit()
    assert reset_result["crawl_runs_deleted"] == 1

    runs = (await db_session.execute(select(CrawlRun))).scalars().all()
    assert len(runs) == 0

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    assert len(entities) == 1
    assert entities[0].canonical_key == "widget"


@pytest.mark.asyncio
@pytest.mark.component
async def test_reset_domain_memory_preserves_knowledge_graph(
    db_session: AsyncSession,
) -> None:
    """reset_domain_memory wipes Domain Memory but leaves the graph intact."""
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"title": "h1"},
        )
    )
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    reset_result = await reset_domain_memory(db_session)
    await db_session.commit()
    assert reset_result["domain_memory_deleted"] == 1

    memory = (await db_session.execute(select(DomainMemory))).scalars().all()
    assert len(memory) == 0

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    assert len(entities) == 1
    assert entities[0].canonical_key == "widget"


@pytest.mark.asyncio
@pytest.mark.component
async def test_reset_application_data_preserves_knowledge_graph(
    db_session: AsyncSession,
    test_user,
) -> None:
    """reset_application_data wipes all buckets but leaves the graph intact."""
    await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"title": "h1"},
        )
    )
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    reset_result = await reset_application_data(db_session)
    await db_session.commit()
    assert reset_result["crawl_runs_deleted"] == 1
    assert reset_result["domain_memory_deleted"] == 1

    runs = (await db_session.execute(select(CrawlRun))).scalars().all()
    memory = (await db_session.execute(select(DomainMemory))).scalars().all()
    assert len(runs) == 0
    assert len(memory) == 0

    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    assert len(entities) == 1
    assert entities[0].canonical_key == "widget"


@pytest.mark.asyncio
@pytest.mark.component
async def test_reset_knowledge_graph_explicit_purge_only(
    db_session: AsyncSession,
    test_user,
) -> None:
    """reset_knowledge_graph is the ONLY reset that removes the graph."""
    await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/widget",
            "surface": "ecommerce_detail",
        },
    )
    db_session.add(
        DomainMemory(
            domain="example.com",
            surface="ecommerce_detail",
            selectors={"title": "h1"},
        )
    )
    entity_id = uuid.uuid4()
    db_session.add(
        KGEntity(
            id=entity_id,
            entity_type="product",
            canonical_key="widget",
            canonical_name="Widget",
        )
    )
    await db_session.commit()

    reset_result = await reset_knowledge_graph(db_session)
    await db_session.commit()
    assert reset_result["kg_entities_deleted"] == 1

    # Crawl and Domain Memory are untouched.
    runs = (await db_session.execute(select(CrawlRun))).scalars().all()
    memory = (await db_session.execute(select(DomainMemory))).scalars().all()
    assert len(runs) == 1
    assert len(memory) == 1

    # Graph is empty.
    entities = (await db_session.execute(select(KGEntity))).scalars().all()
    assert len(entities) == 0
