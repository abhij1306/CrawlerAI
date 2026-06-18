from __future__ import annotations

from app.services.extraction_v2.collectors._helpers import evidence, html_soup
from app.services.extraction_v2.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class MicrodataCollector:
    collector_id = "microdata"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, soup = html_soup(bundle, artifacts)
        mapping = {"name": "product.title", "brand": "product.brand", "description": "product.description", "sku": "product.sku", "price": "offer.price", "priceCurrency": "offer.currency", "availability": "offer.availability", "image": "asset.image_url"}
        out: list[Evidence] = []
        for prop, fact in mapping.items():
            for tag in soup.select(f'[itemprop="{prop}"]'):
                value = str(tag.get("content") or tag.get("src") or tag.get_text(" ", strip=True)).strip()
                if not value:
                    continue
                group = "offer:microdata:product" if fact.startswith("offer.") else None
                hint = EntityHint(entity_type="offer" if fact.startswith("offer.") else "asset" if fact.startswith("asset.") else "product")
                out.append(evidence(bundle, "microdata", "microdata", fact, value, SourceLocator(kind="css_selector", value=f'[itemprop="{prop}"]'), group_id=group, hint=hint, confidence=0.75))
        return tuple(out)
