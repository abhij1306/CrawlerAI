from __future__ import annotations

from typing import Literal

from app.extraction.collectors._helpers import evidence, html_doc, json_objects
from app.extraction.collectors.js_state import network_row
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class MicrodataCollector:
    collector_id = "microdata"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        fields = {"name": "product.title", "brand": "product.brand", "description": "product.description", "sku": "product.sku", "price": "offer.price", "priceCurrency": "offer.currency", "availability": "offer.availability", "image": "asset.image_url"}
        out: list[Evidence] = []
        for prop, fact in fields.items():
            for tag in doc.css(f'[itemprop="{prop}"]'):
                value = str(tag.attribute("content") or tag.attribute("src") or tag.text()).strip()
                if value:
                    out.append(_metadata_evidence(bundle, "microdata", fact, value, f'[itemprop="{prop}"]', 0.75))
        return tuple(out)


class OpenGraphCollector:
    collector_id = "opengraph"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        fields = {"og:title": "product.title", "og:description": "product.description", "og:url": "product.url", "product:brand": "product.brand", "product:price:amount": "offer.price", "product:price:currency": "offer.currency", "og:image": "asset.image_url"}
        out: list[Evidence] = []
        for prop, fact in fields.items():
            for tag in doc.css(f'meta[property="{prop}"], meta[name="{prop}"]'):
                value = str(tag.attribute("content") or "").strip()
                if value:
                    out.append(_metadata_evidence(bundle, "opengraph", fact, value, f'meta[property="{prop}"]', 0.65))
        return tuple(out)


class NetworkCollector:
    collector_id = "network"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        out: list[Evidence] = []
        for ref in bundle.artifacts:
            if ref.artifact_type != "network_json":
                continue
            for path, obj in json_objects(artifacts.read_json(ref)):
                if isinstance(obj, dict):
                    out.extend(
                        network_row(
                            bundle,
                            ref.artifact_id,
                            path,
                            obj,
                            collector_id="network",
                        )
                    )
        return tuple(out)


def _metadata_evidence(bundle, collector_id: str, fact_type: str, value: str, selector: str, confidence: float) -> Evidence:
    entity_type: Literal["product", "offer", "asset"] = "offer" if fact_type.startswith("offer.") else "asset" if fact_type.startswith("asset.") else "product"
    group = f"offer:{collector_id}:product_price" if fact_type.startswith("offer.") else None
    return evidence(bundle, collector_id, collector_id, fact_type, value, SourceLocator(kind="css_selector", value=selector), group_id=group, hint=EntityHint(entity_type=entity_type), confidence=confidence)
