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


def _subject_url_codes(url: object) -> frozenset[str]:
    """Query-aware identity codes for a subject/capture URL.

    Unlike a host+path key, ``detail_identity_codes_from_url`` folds query params
    into the identity (``id=123`` -> ``ID123``), so ``/job?id=123`` and
    ``/job?id=456`` stay distinct. Very short ids (below the code-length floor)
    yield no codes, which surfaces as honest ambiguity downstream.
    """
    return frozenset(detail_identity_codes_from_url(str(url or "").strip()))


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
    capture URL by query-aware identity codes. Returns the sole matching subject;
    returns ``None`` (honest ambiguity) when no subject matches, when several
    distinct subjects still share the requested codes, or when no distinguishing
    codes exist at all (e.g. short ids yielding empty code sets)."""
    wanted: set[str] = set()
    for url in (request.capture.final_url, request.capture.requested_url):
        wanted |= _subject_url_codes(url)
    if not wanted:
        return None
    codes_by_subject: dict[str, set[str]] = {subject_id: set() for subject_id in graph}
    for row in evidence:
        if row.subject_id not in codes_by_subject:
            continue
        if _subject_declares_url(row):
            codes_by_subject[row.subject_id] |= _subject_url_codes(row.value)
    matched = [
        subject_id for subject_id in graph if codes_by_subject[subject_id] & wanted
    ]
    return matched[0] if len(matched) == 1 else None


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
