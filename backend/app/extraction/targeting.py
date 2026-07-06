from __future__ import annotations

from typing import Any

from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    RejectedEntity,
    TargetSelection,
)
from app.core.records.url_identity import (
    detail_identity_codes_from_url,
    detail_url_resource_identity,
)
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
    rejected_identity_roots = _identity_mismatched_roots(graph, evidence, request)
    selected = (
        _select_product_by_url(
            graph,
            evidence,
            request,
            rejected_identity_roots=rejected_identity_roots,
        )
        if root_ids
        else None
    )
    if selected and rejected_identity_roots and _root_is_url_only(
        graph, evidence, selected
    ):
        selected = None
    if selected is None and len(root_ids) == 1 and not rejected_identity_roots:
        selected = root_ids[0]
    return TargetSelection(
        status=_commerce_target_status(
            graph, evidence, root_ids, selected, rejected_identity_roots
        ),
        root_entity_ids=root_ids,
        selected_root_entity_id=selected,
        rejected_roots=tuple(
            RejectedEntity(
                entity_id=entity_id,
                reason="identity_mismatch"
                if entity_id in rejected_identity_roots
                else "not_selected_root",
            )
            for entity_id in root_ids
            if entity_id != selected
        ),
    )


def _commerce_target_status(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    root_ids: tuple[str, ...],
    selected: str | None,
    rejected_identity_roots: set[str],
) -> str:
    if selected:
        return "resolved"
    if not root_ids or set(root_ids) <= rejected_identity_roots:
        return "missing"
    if rejected_identity_roots and all(
        entity_id in rejected_identity_roots
        or _root_is_url_only(graph, evidence, entity_id)
        for entity_id in root_ids
    ):
        return "missing"
    return "ambiguous"


def select_subject_targets(
    graph: tuple[str, ...],
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    spec: SurfaceSpec,
) -> TargetSelection:
    del evidence
    if spec.cardinality == "one" and len(graph) > 1:
        return TargetSelection(
            status="ambiguous",
            root_entity_ids=tuple(graph),
            rejected_roots=tuple(
                RejectedEntity(entity_id=entity_id, reason="competing_detail_root")
                for entity_id in graph
            ),
        )
    roots = graph[: request.max_records] if spec.cardinality == "many" else graph[:1]
    return TargetSelection(
        status="resolved" if roots else "missing",
        root_entity_ids=tuple(roots),
        selected_root_entity_id=roots[0]
        if spec.cardinality == "one" and roots
        else None,
    )


def scoped_graph(graph_state: Any, target: TargetSelection) -> Any:
    if isinstance(graph_state, tuple) and all(
        isinstance(item, str) for item in graph_state
    ):
        selected_ids = set(target.root_entity_ids)
        return tuple(item for item in graph_state if item in selected_ids)
    if not isinstance(graph_state, EntitySet):
        return graph_state
    selected = target.selected_root_entity_id
    if not selected:
        if target.status == "missing" or any(
            row.reason == "identity_mismatch" for row in target.rejected_roots
        ):
            return EntitySet()
        return graph_state
    return _scoped_entity_graph(graph_state, selected)


def _scoped_entity_graph(graph_state: EntitySet, selected: str) -> EntitySet:
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
        option_catalogs=tuple(
            catalog
            for catalog in graph_state.option_catalogs
            if catalog.product_entity_id == selected
        ),
    )


def _select_product_by_url(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
    *,
    rejected_identity_roots: set[str] | None = None,
) -> str | None:
    by_id = {row.evidence_id: row for row in evidence}
    wanted = {request.capture.final_url, request.capture.requested_url}
    wanted_product_ids = {
        code for url in wanted for code in detail_identity_codes_from_url(url)
    }
    wanted_resource_ids = {
        resource_id
        for url in wanted
        if (resource_id := detail_url_resource_identity(url))
    }
    complete_offer_products = _products_with_complete_offers(graph)
    scored: list[tuple[tuple[int, int, int, int, int, int, int], str]] = []
    for product in graph.products:
        if product.entity_id in (rejected_identity_roots or set()):
            continue
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
        resource_ids = {
            resource_id
            for url in urls
            if (resource_id := detail_url_resource_identity(url))
        }
        rank = (
            int(bool(resource_ids & wanted_resource_ids)),
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


def _identity_mismatched_roots(
    graph: EntitySet,
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
) -> set[str]:
    wanted_resource_ids = {
        resource_id
        for url in (request.capture.final_url, request.capture.requested_url)
        if (resource_id := detail_url_resource_identity(url))
    }
    if not wanted_resource_ids:
        return set()
    by_id = {row.evidence_id: row for row in evidence}
    mismatched: set[str] = set()
    for product in graph.products:
        product_url_ids = product.attribute_evidence.get("product.url", ())
        captured_resource_ids = {
            resource_id
            for evidence_id in product_url_ids
            if (row := by_id.get(evidence_id)) is not None
            if row.collector_id != "url"
            if (resource_id := detail_url_resource_identity(str(row.value)))
        }
        if captured_resource_ids and captured_resource_ids.isdisjoint(
            wanted_resource_ids
        ):
            mismatched.add(product.entity_id)
            continue
        resource_ids = {
            resource_id
            for evidence_id in product_url_ids
            if (row := by_id.get(evidence_id)) is not None
            if (resource_id := detail_url_resource_identity(str(row.value)))
        }
        if resource_ids and resource_ids.isdisjoint(wanted_resource_ids):
            mismatched.add(product.entity_id)
    return mismatched


def _root_is_url_only(
    graph: EntitySet, evidence: tuple[Evidence, ...], entity_id: str
) -> bool:
    product = next(
        (row for row in graph.products if row.entity_id == entity_id),
        None,
    )
    if product is None:
        return False
    by_id = {row.evidence_id: row for row in evidence}
    rows = tuple(
        by_id[evidence_id]
        for evidence_ids in product.attribute_evidence.values()
        for evidence_id in evidence_ids
        if evidence_id in by_id
    )
    return bool(rows) and all(row.collector_id == "url" for row in rows)


def _products_with_complete_offers(graph: EntitySet) -> set[str]:
    return {
        offer.product_entity_id
        for offer in graph.offers
        if offer.fact_evidence.get("offer.price")
        and offer.fact_evidence.get("offer.currency")
    }
