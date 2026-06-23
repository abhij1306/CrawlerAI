from __future__ import annotations

from typing import Any

from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    RejectedEntity,
    TargetSelection,
)
from app.core.records.url_identity import detail_identity_codes_from_url
from app.extraction.entities import EntitySet
from app.extraction.surfaces import SurfaceSpec


def select_commerce_target(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> TargetSelection:
    del spec
    root_ids = tuple(product.entity_id for product in graph.products)
    selected = _select_product_by_url(graph, evidence, request) if root_ids else None
    if selected is None and len(root_ids) == 1:
        selected = root_ids[0]
    return TargetSelection(
        status="resolved" if selected else "missing" if not root_ids else "ambiguous",
        root_entity_ids=root_ids,
        selected_root_entity_id=selected,
        rejected_roots=tuple(
            RejectedEntity(entity_id=entity_id, reason="not_selected_root")
            for entity_id in root_ids
            if entity_id != selected
        ),
    )


def select_subject_targets(
    graph: tuple[str, ...],
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> TargetSelection:
    del evidence
    roots = graph[: request.max_records] if spec.cardinality == "many" else graph[:1]
    return TargetSelection(
        status="resolved" if roots else "missing",
        root_entity_ids=tuple(roots),
        selected_root_entity_id=roots[0]
        if spec.cardinality == "one" and roots
        else None,
    )


def scoped_graph(graph_state: Any, target: TargetSelection) -> Any:
    if not isinstance(graph_state, EntitySet):
        return graph_state
    selected = target.selected_root_entity_id
    if not selected:
        return graph_state
    return EntitySet(
        products=tuple(
            product for product in graph_state.products if product.entity_id == selected
        ),
        variants=tuple(
            variant
            for variant in graph_state.variants
            if variant.product_entity_id == selected
        ),
        offers=tuple(
            offer for offer in graph_state.offers if offer.product_entity_id == selected
        ),
        assets=tuple(
            asset for asset in graph_state.assets if asset.product_entity_id == selected
        ),
        product_option_metadata=graph_state.product_option_metadata,
    )


def _select_product_by_url(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
) -> str | None:
    by_id = {row.evidence_id: row for row in evidence}
    wanted = {request.capture.final_url, request.capture.requested_url}
    wanted_product_ids = {
        code
        for url in wanted
        for code in detail_identity_codes_from_url(url)
    }
    complete_offer_products = _products_with_complete_offers(graph)
    scored: list[tuple[tuple[int, int, int, int, int, int], str]] = []
    for product in graph.products:
        urls = {
            str(by_id[evidence_id].value)
            for evidence_id in product.attribute_evidence.get("product.url", ())
            if evidence_id in by_id
        }
        product_ids = {
            str(hint.product_id)
            for evidence_ids in product.attribute_evidence.values()
            for evidence_id in evidence_ids
            if evidence_id in by_id
            and (hint := by_id[evidence_id].entity_hint) is not None
            and hint.product_id
        }
        rank = (
            int(bool(urls & wanted)),
            int(bool(product_ids & wanted_product_ids)),
            int(product.entity_id in complete_offer_products),
            int(bool(product.offer_ids)),
            int(bool(product.attribute_evidence.get("product.title"))),
            len(product.attribute_evidence),
        )
        if any(rank):
            scored.append((rank, product.entity_id))
    return max(scored, key=lambda item: (item[0], item[1]))[1] if scored else None


def _products_with_complete_offers(graph: EntitySet) -> set[str]:
    return {
        offer.product_entity_id
        for offer in graph.offers
        if offer.fact_evidence.get("offer.price")
        and offer.fact_evidence.get("offer.currency")
    }
