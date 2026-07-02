"""Offline label-decorated view of the runtime compact representation."""

from __future__ import annotations

from app.core.config.evaluation import COMPACT_REPRESENTATION_MAX_NODES
from app.evaluation.schema import GroundedLabel, GroundingReference
from app.extraction.documents import HtmlDocument
from app.extraction.model_runtime import (
    RuntimeCompactNode,
    RuntimeCompactPage,
    RuntimeCompactSource,
    build_runtime_compact_page,
)


class CompactSourceLineage(RuntimeCompactSource):
    pass


class CompactNode(RuntimeCompactNode):
    label_ids: tuple[str, ...] = ()
    region_refs: tuple[str, ...] = ()


class CompactPageRepresentation(RuntimeCompactPage):
    source: CompactSourceLineage
    nodes: tuple[CompactNode, ...]
    labels: tuple[GroundedLabel, ...] = ()
    grounding_references: tuple[GroundingReference, ...] = ()


def build_compact_page_representation(
    *,
    html: str,
    artifact_id: str,
    labels: tuple[GroundedLabel, ...] = (),
    market_tags: tuple[str, ...] = (),
    max_nodes: int = COMPACT_REPRESENTATION_MAX_NODES,
) -> CompactPageRepresentation:
    """Build the runtime representation, then attach offline truth references."""
    runtime_page = build_runtime_compact_page(
        html=html,
        artifact_id=artifact_id,
        market_tags=market_tags,
        max_nodes=max_nodes,
    )
    label_refs = _label_refs(labels, HtmlDocument(artifact_id, html), artifact_id)
    nodes = tuple(
        CompactNode(
            **node.model_dump(),
            label_ids=tuple(sorted(label_refs["paths"].get(node.path, ()))),
            region_refs=tuple(sorted(label_refs["regions"].get(node.path, ()))),
        )
        for node in runtime_page.nodes
    )
    return CompactPageRepresentation(
        source=CompactSourceLineage(**runtime_page.source.model_dump()),
        nodes=nodes,
        labels=labels,
        grounding_references=_unique_grounding_references(labels),
        market_tags=runtime_page.market_tags,
        truncated=runtime_page.truncated,
    )


def _label_refs(
    labels: tuple[GroundedLabel, ...],
    document: HtmlDocument,
    artifact_id: str,
) -> dict[str, dict[str, set[str]]]:
    paths: dict[str, set[str]] = {}
    regions: dict[str, set[str]] = {}
    for label in labels:
        for reference in label.grounding:
            if reference.artifact_id != artifact_id:
                continue
            if reference.kind == "path":
                paths.setdefault(reference.locator, set()).add(label.label_id)
            elif reference.kind == "node":
                for path in _node_reference_paths(reference, document):
                    paths.setdefault(path, set()).add(label.label_id)
            elif reference.kind == "region" and reference.locator.startswith("/"):
                regions.setdefault(reference.locator, set()).add(label.label_id)
    return {"paths": paths, "regions": regions}


def _node_reference_paths(
    reference: GroundingReference, document: HtmlDocument
) -> tuple[str, ...]:
    locator = reference.locator.strip()
    if locator.startswith("/"):
        return (locator,)
    if not locator.startswith("css:"):
        return ()
    selector = locator.removeprefix("css:").strip()
    if not selector:
        return ()
    try:
        return tuple(node.dom_path() for node in document.css(selector))
    except (RuntimeError, ValueError):
        return ()


def _unique_grounding_references(
    labels: tuple[GroundedLabel, ...],
) -> tuple[GroundingReference, ...]:
    unique: dict[tuple[object, ...], GroundingReference] = {}
    for label in labels:
        for reference in label.grounding:
            box = reference.bounding_box
            key = (
                reference.kind,
                reference.artifact_id,
                reference.locator,
                box.x if box else None,
                box.y if box else None,
                box.width if box else None,
                box.height if box else None,
            )
            unique.setdefault(key, reference)
    return tuple(unique.values())
