from __future__ import annotations

from typing import Literal

from app.core.config import variant_policy
from app.core.config.field_mappings import (
    ECOMMERCE_MICRODATA_FACT_TYPES,
    ECOMMERCE_OPENGRAPH_FACT_TYPES,
)
from app.extraction.collectors._helpers import evidence, html_doc, json_objects
from app.extraction.collectors.dom_scoping import (
    node_context_excluded,
    node_within_roots,
    product_root_nodes,
)
from app.extraction.collectors.js_state import (
    StructuredHarvestResult,
    budget_outcome,
    network_row,
    path_is_nested_sibling_product,
    prioritize_evidence_rows,
    root_admits_path,
    select_product_roots,
)
from app.core.records.structured_variant_state import (
    variant_axis_hints,
    with_parent_variant_axes,
)
from app.core.config.extraction_rules import MAX_EVIDENCE_PER_SOURCE_OBJECT
from app.extraction.contracts import (
    CaptureBundle,
    CollectorOutcome,
    EntityHint,
    Evidence,
    SourceLocator,
)


class MicrodataCollector:
    collector_id = "microdata"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        root_ids = {node.identity() for node in product_root_nodes(doc)}
        for prop, fact in ECOMMERCE_MICRODATA_FACT_TYPES.items():
            for tag in doc.css(f'[itemprop="{prop}"]'):
                if fact.startswith("product.") and (
                    node_context_excluded(tag)
                    or (root_ids and not node_within_roots(tag, root_ids))
                ):
                    continue
                value = str(
                    tag.attribute("content") or tag.attribute("src") or tag.text()
                ).strip()
                if value:
                    out.append(
                        _metadata_evidence(
                            bundle,
                            "microdata",
                            fact,
                            value,
                            f'[itemprop="{prop}"]',
                            0.75,
                        )
                    )
        return tuple(out)


class OpenGraphCollector:
    collector_id = "opengraph"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        for prop, fact in ECOMMERCE_OPENGRAPH_FACT_TYPES.items():
            for tag in doc.css(f'meta[property="{prop}"], meta[name="{prop}"]'):
                value = str(tag.attribute("content") or "").strip()
                if value:
                    out.append(
                        _metadata_evidence(
                            bundle,
                            "opengraph",
                            fact,
                            value,
                            f'meta[property="{prop}"]',
                            0.65,
                        )
                    )
        return tuple(out)


class _JsonArtifactCollector:
    collector_id = "network"
    collector_version = "1"
    artifact_type = "network_json"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        return self.harvest(bundle, artifacts).evidence

    def harvest(
        self,
        bundle: CaptureBundle,
        artifacts,
        *,
        requested_fields: tuple[str, ...] = (),
    ) -> StructuredHarvestResult:
        out: list[Evidence] = []
        outcomes: list[CollectorOutcome] = []
        admitted_source_objects = 0
        for ref in bundle.artifacts:
            if ref.artifact_type != self.artifact_type:
                continue
            objects = tuple(json_objects(artifacts.read_json(ref)))
            axis_hints = variant_axis_hints(objects)
            selection = select_product_roots(objects, bundle.final_url)
            for path, obj in objects:
                if not root_admits_path(selection, path):
                    continue
                if isinstance(obj, dict) and path_is_nested_sibling_product(
                    selection, path, obj, bundle.final_url
                ):
                    continue
                if isinstance(obj, dict):
                    admitted_source_objects += 1
                    enriched = with_parent_variant_axes(
                        obj,
                        axis_hints.get(path, ()),
                    )
                    rows, dropped = prioritize_evidence_rows(
                        network_row(
                            bundle,
                            ref.artifact_id,
                            path,
                            enriched,
                            collector_id=self.collector_id,
                        ),
                        requested_fields=requested_fields,
                        limit=MAX_EVIDENCE_PER_SOURCE_OBJECT,
                    )
                    if dropped:
                        outcomes.append(
                            budget_outcome(
                                variant_policy.STRUCTURED_EVIDENCE_BUDGET_REASON,
                                artifact_id=ref.artifact_id,
                                root_path=path,
                                count=len(rows) + len(dropped),
                                limit=MAX_EVIDENCE_PER_SOURCE_OBJECT,
                                dropped=dropped,
                            ).model_copy(update={"collector_id": self.collector_id})
                        )
                    out.extend(rows)
        outcomes.append(
            CollectorOutcome(
                collector_id=self.collector_id,
                outcome="produced_evidence" if out else "no_match",
                evidence_count=len(out),
            )
        )
        return StructuredHarvestResult(
            evidence=tuple(out),
            outcomes=tuple(outcomes),
            admitted_source_objects=admitted_source_objects,
        )


class AdapterCollector(_JsonArtifactCollector):
    collector_id = "adapter"
    artifact_type = "adapter_json"


class NetworkCollector(_JsonArtifactCollector):
    pass


def _metadata_evidence(
    bundle,
    collector_id: str,
    fact_type: str,
    value: str,
    selector: str,
    confidence: float,
) -> Evidence:
    entity_type: Literal["product", "offer", "asset"] = (
        "offer"
        if fact_type.startswith("offer.")
        else "asset"
        if fact_type.startswith("asset.")
        else "product"
    )
    group = (
        f"offer:{collector_id}:product_price"
        if fact_type.startswith("offer.")
        else None
    )
    product_subject = evidence(
        bundle,
        "url",
        "url",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="url_component", value="url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        directness="inferred",
        confidence=0.0,
    ).subject_id
    return evidence(
        bundle,
        collector_id,
        collector_id,
        fact_type,
        value,
        SourceLocator(kind="css_selector", value=selector),
        group_id=group,
        hint=EntityHint(entity_type=entity_type),
        confidence=confidence,
        parent_subject_id=product_subject
        if entity_type in {"offer", "asset"}
        else None,
        parent_scope="product" if entity_type in {"offer", "asset"} else None,
    )
