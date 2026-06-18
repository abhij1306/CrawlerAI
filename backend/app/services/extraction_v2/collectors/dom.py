from __future__ import annotations

from app.services.extraction_v2.collectors._helpers import evidence, html_soup
from app.services.extraction_v2.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class DomCollector:
    collector_id = "dom"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, soup = html_soup(bundle, artifacts)
        out: list[Evidence] = []
        selectors = [("h1", "product.title"), ('[data-price]', "offer.price"), ('[data-currency]', "offer.currency"), ('[data-sku]', "product.sku")]
        for selector, fact in selectors:
            for tag in soup.select(selector):
                attr = "data-price" if "price" in selector else "data-currency" if "currency" in selector else "data-sku" if "sku" in selector else None
                value = str(tag.get(attr) if attr else tag.get_text(" ", strip=True)).strip()
                if not value:
                    continue
                group = "offer:dom:product" if fact.startswith("offer.") else None
                hint = EntityHint(entity_type="offer" if fact.startswith("offer.") else "product")
                out.append(evidence(bundle, "dom", "dom", fact, value, SourceLocator(kind="css_selector", value=selector), group_id=group, hint=hint, confidence=0.6))
        for img in soup.select("main img[src], img[data-product-image][src]"):
            src = str(img.get("src") or "").strip()
            if src:
                out.append(evidence(bundle, "dom", "dom", "asset.image_url", src, SourceLocator(kind="css_selector", value="img[src]"), hint=EntityHint(entity_type="asset"), confidence=0.55))
        return tuple(out)
