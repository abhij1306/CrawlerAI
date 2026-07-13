from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.extraction_memory.recipe_executor import execute_recipe
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    CommerceDetailProjection,
    CommerceListingProjection,
    Evidence,
    EntityHint,
    HarvestResult,
    JobDetailProjection,
    JobListingProjection,
    PublicationEntry,
    ResolutionEnvelope,
    SourceLocator,
)
from app.extraction.recipe_compiler import compile_recipe_candidate
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


class _Source:
    def __init__(self, surface: Surface, evidence, projection) -> None:
        self.surface = surface
        self.evidence = tuple(evidence)
        self.projection = projection
        self.publish_calls = 0

    def harvest(self, request):
        return HarvestResult(surface=self.surface, evidence=self.evidence)

    def resolve(self, request, harvest):
        return ResolutionEnvelope(surface=self.surface, publication=self.projection)

    def publish(self, resolution):
        self.publish_calls += 1
        raise AssertionError("compiler must not publish")


def _evidence(request, *, entity: str, field: str, pointer: str, value) -> Evidence:
    evidence_id = stable_id("ev", entity, field, pointer)
    return Evidence(
        evidence_id=evidence_id,
        bundle_id=request.capture.bundle_id,
        artifact_id="network_0",
        collector_id="listing_structured_floor",
        collector_version="1",
        fact_type=("job" if request.surface.value.startswith("job") else "product")
        + f".{field}",
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=pointer),
        entity_hint=EntityHint(
            entity_type="job" if request.surface.value.startswith("job") else "product"
        ),
        directness="embedded",
        confidence=0.9,
        surface=request.surface,
        subject_id=entity,
        subject_scope="job" if request.surface.value.startswith("job") else "product",
    )


def _entry(entity: str, field: str, row: Evidence, value) -> PublicationEntry:
    prefix = "record" if "listing" not in row.surface.value else f"record[{entity}]"
    return PublicationEntry(
        path=f"{prefix}.{field}",
        entity_id=entity,
        value=value,
        selected_fact_id=f"selected-{row.evidence_id}",
        evidence_ids=(row.evidence_id,),
        collector_ids=(row.collector_id,),
    )


def _case(surface: Surface):
    listing = "listing" in surface.value
    job = surface.value.startswith("job")
    page_url = "https://jobs.test/openings" if job else "https://shop.test/products/red"
    items = (
        [
            {"title": "Engineer One", "url": "https://jobs.test/jobs/1"},
            {"title": "Engineer Two", "url": "https://jobs.test/jobs/2"},
        ]
        if job
        else [
            {"title": "Trail Red", "url": "https://shop.test/products/red"},
            {"title": "Trail Blue", "url": "https://shop.test/products/blue"},
        ]
    )
    if not listing:
        items = [
            {
                "title": "Engineer One" if job else "Trail Red",
                "url": page_url,
            }
        ]
    payload = {"items": items}
    request = fixture_request_from_inputs(
        surface,
        "<main></main>",
        page_url,
        max_records=10,
        network_payloads=[{"body": payload}],
    )
    rows = []
    entries = []
    for index, item in enumerate(items):
        entity = f"entity-{index}"
        for field in ("title", "url"):
            row = _evidence(
                request,
                entity=entity,
                field=field,
                pointer=f"/items/{index}/{field}",
                value=item[field],
            )
            rows.append(row)
            entries.append(_entry(entity, field, row, item[field]))
    if surface is Surface.ECOMMERCE_DETAIL:
        projection = CommerceDetailProjection(
            record_entity_id="entity-0", entries=tuple(entries)
        )
    elif surface is Surface.JOB_DETAIL:
        projection = JobDetailProjection(
            record_entity_id="entity-0", entries=tuple(entries)
        )
    elif surface is Surface.ECOMMERCE_LISTING:
        projection = CommerceListingProjection(
            record_entity_ids=tuple(f"entity-{i}" for i in range(len(items))),
            entries=tuple(entries),
        )
    else:
        projection = JobListingProjection(
            record_entity_ids=tuple(f"entity-{i}" for i in range(len(items))),
            entries=tuple(entries),
        )
    return request, _Source(surface, rows, projection), items


@pytest.mark.parametrize("surface", tuple(Surface))
def test_compiler_emits_candidate_then_executor_replays_capture(
    surface: Surface,
) -> None:
    request, source, items = _case(surface)

    discovery = compile_recipe_candidate(request, source)

    assert discovery.failure_code is None
    assert discovery.candidate is not None
    assert source.publish_calls == 0
    execution = execute_recipe(request, discovery.candidate.recipe)
    assert execution.failure_code is None
    assert execution.records == tuple(items)


def test_compiler_accepts_grounded_singleton_listing() -> None:
    request, source, items = _case(Surface.ECOMMERCE_LISTING)
    source.evidence = tuple(
        row.model_copy(update={"collector_id": "listing_dom_floor"})
        for row in source.evidence[:2]
    )
    source.projection = CommerceListingProjection(
        record_entity_ids=("entity-0",),
        entries=tuple(source.projection.entries[:2]),
    )

    discovery = compile_recipe_candidate(request, source)

    assert discovery.candidate is not None
    assert execute_recipe(request, discovery.candidate.recipe).records == (items[0],)
    assert source.publish_calls == 0


def test_default_dom_listing_compiles_repeated_relative_bindings() -> None:
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        """
        <main>
          <article class="product-card">
            <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
          </article>
          <article class="product-card">
            <a href="/products/day-pack"><h2>Day Pack</h2></a>
          </article>
        </main>
        """,
        "https://shop.test/collections/all",
        max_records=5,
    )

    discovery = compile_recipe_candidate(request)

    assert discovery.candidate is not None
    execution = execute_recipe(request, discovery.candidate.recipe)
    assert execution.failure_code is None
    assert execution.records == (
        {"url": "https://shop.test/products/trail-shoe", "title": "Trail Shoe"},
        {"url": "https://shop.test/products/day-pack", "title": "Day Pack"},
    )


def test_compiler_owner_cannot_import_publication_or_public_records() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "extraction"
        / "recipe_compiler.py"
    )
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "app.extraction.publication" not in imports
    assert "PublicRecord" not in source
    assert "PublicationResult" not in source
