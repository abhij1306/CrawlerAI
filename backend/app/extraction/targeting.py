from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    RejectedEntity,
    TargetSelection,
    TargetStatus,
)
from app.core.records.url_identity import (
    detail_identity_codes_from_url,
    detail_url_product_slug,
    detail_url_resource_identity,
    normalize_variant_identity,
    variant_identity_tokens,
)
from app.core.config.extraction_rules import DETAIL_IDENTITY_QUERY_KEYS
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
    if (
        selected
        and rejected_identity_roots
        and _root_is_url_only(graph, evidence, selected)
    ):
        selected = None
    if selected is None and len(root_ids) == 1 and not rejected_identity_roots:
        selected = root_ids[0]
    query_codes = _requested_variant_query_codes((request.capture.final_url, request.capture.requested_url))
    selected_variant = _select_requested_variant(graph, selected, query_codes)
    status = (
        "ambiguous"
        if selected is not None and query_codes and selected_variant is None
        else _commerce_target_status(
            graph, evidence, root_ids, selected, rejected_identity_roots
        )
    )
    return TargetSelection(
        status=status,
        root_entity_ids=root_ids,
        selected_root_entity_id=selected,
        selected_variant_entity_id=selected_variant,
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
) -> TargetStatus:
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
    if target.status == "ambiguous":
        return EntitySet()
    selected = target.selected_root_entity_id
    if not selected:
        if target.status == "missing" or any(
            row.reason == "identity_mismatch" for row in target.rejected_roots
        ):
            return EntitySet()
        return graph_state
    return _scoped_entity_graph(
        graph_state, selected, selected_variant=target.selected_variant_entity_id
    )


def _scoped_entity_graph(
    graph_state: EntitySet,
    selected: str,
    *,
    selected_variant: str | None = None,
) -> EntitySet:
    variants = tuple(
        variant
        for variant in graph_state.variants
        if variant.product_entity_id == selected
    )
    selected_variant_ids = {selected_variant} if selected_variant else set()
    if selected_variant:
        variants = tuple(
            variant for variant in variants if variant.entity_id == selected_variant
        )
    offers = tuple(
        offer
        for offer in graph_state.offers
        if offer.product_entity_id == selected
        and (not selected_variant or offer.variant_entity_id in selected_variant_ids)
    )
    assets = tuple(
        asset
        for asset in graph_state.assets
        if asset.product_entity_id == selected
        and (not selected_variant or asset.variant_entity_id in selected_variant_ids)
    )
    return EntitySet(
        products=tuple(
            product for product in graph_state.products if product.entity_id == selected
        ),
        variants=variants,
        offers=offers,
        assets=assets,
        product_option_metadata=graph_state.product_option_metadata,
        option_catalogs=tuple(
            catalog
            for catalog in graph_state.option_catalogs
            if catalog.product_entity_id == selected
        ),
    )


def _select_requested_variant(
    graph: EntitySet,
    selected_product_id: str | None,
    query_codes: set[str],
) -> str | None:
    if not selected_product_id:
        return None
    variants = tuple(
        variant
        for variant in graph.variants
        if variant.product_entity_id == selected_product_id
    )
    if not variants:
        return None
    explicit = tuple(
        variant for variant in variants if variant.selected and variant.identity_keys
    )
    if len(explicit) == 1:
        return explicit[0].entity_id

    if not query_codes:
        return None
    scores = {
        variant.entity_id: len(
            query_codes
            & variant_identity_tokens(variant.identity_keys, variant.option_values)
        )
        for variant in variants
    }
    highest = max(scores.values(), default=0)
    matches = tuple(entity_id for entity_id, score in scores.items() if score == highest)
    return matches[0] if highest and len(matches) == 1 else None


def _requested_variant_query_codes(requested_urls) -> set[str]:
    return {
        token
        for url in requested_urls
        for key, value in parse_qsl(urlsplit(str(url or "")).query)
        if key.casefold() in DETAIL_IDENTITY_QUERY_KEYS
        for token in (normalize_variant_identity(value),)
        if token
    }


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
    wanted_slugs = {
        slug
        for url in (request.capture.final_url, request.capture.requested_url)
        if (slug := detail_url_product_slug(url))
    }
    by_id = {row.evidence_id: row for row in evidence}
    mismatched: set[str] = set()
    for product in graph.products:
        product_url_ids = product.attribute_evidence.get("product.url", ())
        captured_rows = [
            row
            for evidence_id in product_url_ids
            if (row := by_id.get(evidence_id)) is not None
            if row.collector_id != "url"
        ]
        # Prefix-independent identity: a captured canonical whose terminal
        # product slug equals the requested URL's is the *same* product even
        # when the whole-path resource id differs (e.g. Shopify captured under
        # /collections/x/products/<slug> vs the /products/<slug> canonical).
        captured_slugs = {
            slug
            for row in captured_rows
            if (slug := detail_url_product_slug(str(row.value)))
        }
        if wanted_slugs and captured_slugs & wanted_slugs:
            continue
        captured_resource_ids = {
            resource_id
            for row in captured_rows
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
