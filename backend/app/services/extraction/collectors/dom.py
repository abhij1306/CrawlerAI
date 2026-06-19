from __future__ import annotations

from app.services.extraction.collectors._helpers import evidence, html_doc
from app.services.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.services.extraction.ids import stable_id


class DomCollector:
    collector_id = "dom"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        product_subject = stable_id("subject", bundle.bundle_id, "product", bundle.final_url)
        selectors = [("h1", "product.title"), ('[data-price]', "offer.price"), ('[data-currency]', "offer.currency"), ('[data-sku]', "product.sku")]
        for selector, fact in selectors:
            for tag in doc.css(selector):
                attr = "data-price" if "price" in selector else "data-currency" if "currency" in selector else "data-sku" if "sku" in selector else None
                value = str(tag.attribute(attr) if attr else tag.text()).strip()
                if not value:
                    continue
                group = "offer:dom:product" if fact.startswith("offer.") else None
                hint = EntityHint(entity_type="offer" if fact.startswith("offer.") else "product")
                subject_id = group if fact.startswith("offer.") else product_subject
                out.append(evidence(bundle, "dom", "dom", fact, value, SourceLocator(kind="css_selector", value=selector), group_id=group, hint=hint, confidence=0.6, subject_id=subject_id, parent_subject_id=product_subject if fact.startswith("offer.") else None))
        for img in doc.css("main img[src], img[data-product-image][src]"):
            src = str(img.attribute("src") or "").strip()
            if src:
                out.append(evidence(bundle, "dom", "dom", "asset.image_url", src, SourceLocator(kind="css_selector", value="img[src]"), hint=EntityHint(entity_type="asset"), confidence=0.55, parent_subject_id=product_subject))
        out.extend(_variant_controls(bundle, doc, product_subject))
        return tuple(out)


def _variant_controls(bundle: CaptureBundle, doc, product_subject: str) -> list[Evidence]:
    out: list[Evidence] = []
    for axis, selectors in {
        "size": ('select[name*="size" i] option', '[data-option-name*="size" i]', '[aria-label*="size" i]'),
        "color": ('select[name*="color" i] option', '[data-option-name*="color" i]', '[aria-label*="color" i]'),
    }.items():
        seen: set[str] = set()
        for selector in selectors:
            for index, tag in enumerate(doc.css(selector)):
                value = str(tag.attribute("value") or tag.attribute("aria-label") or tag.text()).strip()
                if not value or value.lower() in {"select", "choose", "size", "color", "colour"}:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                subject_id = f"variant:dom:{axis}:{index}:{key}"
                hint = EntityHint(entity_type="variant", option_values={axis: value})
                out.append(
                    evidence(
                        bundle,
                        "dom",
                        "dom",
                        f"variant.option.{axis}",
                        value,
                        SourceLocator(kind="css_selector", value=selector, preview=value[:120]),
                        group_id=subject_id,
                        hint=hint,
                        confidence=0.58,
                        subject_id=subject_id,
                        parent_subject_id=product_subject,
                    )
                )
    return out
