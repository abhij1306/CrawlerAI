from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse

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

# A plain ``job.url`` claims subject identity only when lifted from structured
# markup (``embedded``/``inferred``); the DOM floor's ``job.url = page_url``
# self-reference (``direct``) trivially matches every requested URL and is
# excluded. An explicit ``job.apply_url`` always claims identity.
_SUBJECT_URL_DECLARED_DIRECTNESS = frozenset({"embedded", "inferred"})


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
    if spec.cardinality == "one" and len(graph) > 1:
        selected = _select_subject_by_url(graph, evidence, request)
        if selected is None:
            return TargetSelection(
                status="ambiguous",
                root_entity_ids=tuple(graph),
                rejected_roots=tuple(
                    RejectedEntity(entity_id=entity_id, reason="competing_detail_root")
                    for entity_id in graph
                ),
            )
        return TargetSelection(
            status="resolved",
            root_entity_ids=(selected,),
            selected_root_entity_id=selected,
            rejected_roots=tuple(
                RejectedEntity(entity_id=entity_id, reason="not_selected_root")
                for entity_id in graph
                if entity_id != selected
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


def _subject_url_identity(url: object) -> str:
    parsed = urlparse(str(url or "").strip())
    host = str(parsed.hostname or "").casefold().strip(".")
    path = unquote(parsed.path).casefold().rstrip("/")
    if not host and not path:
        return ""
    return f"{host}{path}"


def _subject_declares_url(row: Evidence) -> bool:
    if row.fact_type == "job.apply_url":
        return True
    return (
        row.fact_type == "job.url"
        and row.directness in _SUBJECT_URL_DECLARED_DIRECTNESS
    )


def _select_subject_by_url(
    graph: tuple[str, ...],
    evidence: tuple[Evidence, ...],
    request: ExtractionRequest,
) -> str | None:
    """Pick the competing detail root whose declared URL matches the requested
    capture URL; when several subjects share that identity, the richest is
    chosen. Returns ``None`` when no subject matches — an honest ambiguity."""
    wanted = {
        identity
        for url in (request.capture.final_url, request.capture.requested_url)
        if (identity := _subject_url_identity(url))
    }
    if not wanted:
        return None
    urls_by_subject: dict[str, set[str]] = {subject_id: set() for subject_id in graph}
    facts_by_subject: dict[str, int] = {subject_id: 0 for subject_id in graph}
    for row in evidence:
        if row.subject_id not in urls_by_subject:
            continue
        facts_by_subject[row.subject_id] += 1
        if _subject_declares_url(row) and (
            identity := _subject_url_identity(row.value)
        ):
            urls_by_subject[row.subject_id].add(identity)
    scored = [
        (facts_by_subject[subject_id], -index, subject_id)
        for index, subject_id in enumerate(graph)
        if urls_by_subject[subject_id] & wanted
    ]
    return max(scored)[2] if scored else None


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


def _products_with_complete_offers(graph: EntitySet) -> set[str]:
    return {
        offer.product_entity_id
        for offer in graph.offers
        if offer.fact_evidence.get("offer.price")
        and offer.fact_evidence.get("offer.currency")
    }
