from __future__ import annotations

from app.services.extraction.collectors._helpers import evidence, html_doc
from app.services.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class OpenGraphCollector:
    collector_id = "opengraph"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        artifact_id = "opengraph"
        fields = {"og:title": "product.title", "og:description": "product.description", "og:url": "product.url", "product:brand": "product.brand", "product:price:amount": "offer.price", "product:price:currency": "offer.currency", "og:image": "asset.image_url"}
        out: list[Evidence] = []
        for prop, fact in fields.items():
            for tag in doc.css(f'meta[property="{prop}"], meta[name="{prop}"]'):
                value = str(tag.attribute("content") or "").strip()
                if not value:
                    continue
                hint = EntityHint(entity_type="offer" if fact.startswith("offer.") else "asset" if fact.startswith("asset.") else "product")
                group = f"offer:{artifact_id}:product_price" if fact.startswith("offer.") else None
                out.append(evidence(bundle, artifact_id, "opengraph", fact, value, SourceLocator(kind="css_selector", value=f'meta[property="{prop}"]'), group_id=group, hint=hint, confidence=0.65))
        return tuple(out)
