from __future__ import annotations

import re

from app.extraction.collectors._helpers import evidence, html_doc
from app.core.config.extraction_rules import (
    DETAIL_BRAND_DOM_SELECTORS,
    DETAIL_BRAND_DOM_VALUE_ATTRIBUTES,
    DETAIL_BRAND_VISIBLE_LABEL_PATTERN,
    DETAIL_DOM_IMAGE_NEGATIVE_SCOPE_TOKENS,
    DETAIL_DOM_IMAGE_POSITIVE_SCOPE_TOKENS,
    DETAIL_IMAGE_SRCSET_ATTRS,
    DETAIL_IMAGE_URL_ATTRS,
    VARIANT_DOM_MAX_LABEL_LENGTH,
    VARIANT_DOM_NOISE_PHRASES,
    VARIANT_DOM_SIZE_LABEL_PATTERN,
    VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
)
from app.core.config.field_mappings import (
    ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
    REQUESTED_FIELD_DOM_SELECTOR_TEMPLATES,
)
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.documents import HtmlNode
from app.extraction.ids import stable_id
from app.core.records.field_policy import normalize_requested_field
from app.core.shared.url_utils import is_utility_image_url

_IMAGE_SCOPE_ATTRIBUTES = (
    "id",
    "class",
    "data-testid",
    "data-component",
    "data-section",
    "aria-label",
    "role",
)


class DomCollector:
    collector_id = "dom"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        out: list[Evidence] = []
        product_subject = stable_id(
            "subject", bundle.bundle_id, "product", bundle.final_url
        )
        selectors = [
            ("h1", "product.title"),
            ("[data-price]", "offer.price"),
            ("[data-currency]", "offer.currency"),
            ("[data-sku]", "product.sku"),
        ]
        for selector, fact in selectors:
            for tag in doc.css(selector):
                attr = (
                    "data-price"
                    if "price" in selector
                    else "data-currency"
                    if "currency" in selector
                    else "data-sku"
                    if "sku" in selector
                    else None
                )
                value = str(tag.attribute(attr) if attr else tag.text()).strip()
                if not value:
                    continue
                group = "offer:dom:product" if fact.startswith("offer.") else None
                hint = EntityHint(
                    entity_type="offer" if fact.startswith("offer.") else "product"
                )
                subject_id = group if fact.startswith("offer.") else product_subject
                out.append(
                    evidence(
                        bundle,
                        "dom",
                        "dom",
                        fact,
                        value,
                        SourceLocator(kind="css_selector", value=selector),
                        group_id=group,
                        hint=hint,
                        confidence=0.6,
                        subject_id=subject_id,
                        parent_subject_id=product_subject
                        if fact.startswith("offer.")
                        else None,
                    )
                )
        out.extend(_product_brand_evidence(bundle, doc, product_subject))
        for img, confidence in _product_image_nodes(doc):
            src = _image_node_url(img)
            locator = SourceLocator(
                kind="css_selector", value=img.stable_locator(), preview=src[:120]
            )
            out.append(
                evidence(
                    bundle,
                    "dom",
                    "dom",
                    "asset.image_url",
                    src,
                    locator,
                    hint=EntityHint(entity_type="asset"),
                    confidence=confidence,
                    parent_subject_id=product_subject,
                )
            )
        out.extend(_variant_controls(bundle, doc, product_subject))
        return tuple(out)


def _product_brand_evidence(
    bundle: CaptureBundle, doc, product_subject: str
) -> tuple[Evidence, ...]:
    rows: list[Evidence] = []
    seen: set[str] = set()
    for selector in DETAIL_BRAND_DOM_SELECTORS:
        for node in doc.css(selector):
            if node.is_hidden():
                continue
            value = _brand_node_value(node)
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            rows.append(
                evidence(
                    bundle,
                    "dom",
                    "dom",
                    "product.brand",
                    value,
                    SourceLocator(
                        kind="css_selector",
                        value=node.stable_locator(),
                        preview=value[:120],
                    ),
                    hint=EntityHint(entity_type="product"),
                    confidence=0.72,
                    subject_id=product_subject,
                    metadata={"brand_evidence_kind": "explicit_product_label"},
                )
            )
    return tuple(rows)


def _brand_node_value(node: HtmlNode) -> str:
    for attribute in DETAIL_BRAND_DOM_VALUE_ATTRIBUTES:
        value = str(node.attribute(attribute) or "").strip()
        if value:
            return value
    text = " ".join(str(node.text() or "").split())
    match = re.fullmatch(DETAIL_BRAND_VISIBLE_LABEL_PATTERN, text, re.IGNORECASE)
    if match is not None:
        return str(match.group("brand") or "").strip()
    context = " ".join(
        str(node.attribute(attribute) or "").casefold()
        for attribute in ("class", "id", "data-testid", "itemprop")
    )
    if any(token in context for token in ("product-brand", "product_brand", "manufacturer")):
        return text if 0 < len(text) <= 80 else ""
    return ""


def _product_image_nodes(doc) -> tuple[tuple[HtmlNode, float], ...]:
    candidates: list[tuple[HtmlNode, str]] = []
    seen: set[int] = set()
    for node in doc.css(
        "main img[src], main img[data-src], main img[data-lazy-src], "
        "main img[data-original], main img[data-image], main img[srcset], "
        "main img[data-srcset], main source[srcset], main source[data-srcset], "
        "img[data-product-image][src], img[data-product-image][data-src]"
    ):
        identity = node.identity()
        src = _image_node_url(node)
        if identity in seen or node.is_hidden() or not src or is_utility_image_url(src):
            continue
        seen.add(identity)
        context = _image_scope_context(node)
        if not any(
            token in context for token in DETAIL_DOM_IMAGE_NEGATIVE_SCOPE_TOKENS
        ):
            candidates.append((node, context))
    scoped = [
        node
        for node, context in candidates
        if node.attribute("data-product-image") is not None
        or any(token in context for token in DETAIL_DOM_IMAGE_POSITIVE_SCOPE_TOKENS)
    ]
    if scoped:
        return tuple((node, 0.58) for node in scoped)
    return tuple((node, 0.5) for node, _ in candidates)


def _image_node_url(node: HtmlNode) -> str:
    for attribute in DETAIL_IMAGE_URL_ATTRS:
        value = str(node.attribute(attribute) or "").strip()
        if value and not is_utility_image_url(value):
            return value
    for attribute in DETAIL_IMAGE_SRCSET_ATTRS:
        value = _largest_srcset_url(str(node.attribute(attribute) or ""))
        if value and not is_utility_image_url(value):
            return value
    return ""


def _largest_srcset_url(value: str) -> str:
    ranked: list[tuple[float, int, str]] = []
    for index, raw_candidate in enumerate(str(value or "").split(",")):
        parts = raw_candidate.strip().rsplit(None, 1)
        if not parts or not parts[0]:
            continue
        url = parts[0]
        rank = float(index)
        if len(parts) == 2 and parts[1][-1:].casefold() in {"w", "x"}:
            try:
                rank = float(parts[1][:-1])
            except ValueError:
                pass
        ranked.append((rank, index, url))
    return max(ranked, default=(0.0, 0, ""))[2]


def _image_scope_context(node: HtmlNode) -> str:
    return " ".join(
        str(current.attribute(attribute) or "").casefold()
        for current in (node, *node.ancestors()[:8])
        for attribute in _IMAGE_SCOPE_ATTRIBUTES
    )


def collect_requested_fields(
    bundle: CaptureBundle,
    artifacts,
    requested_fields: tuple[str, ...],
) -> tuple[Evidence, ...]:
    _, doc = html_doc(bundle, artifacts)
    product_subject = stable_id(
        "subject", bundle.bundle_id, "product", bundle.final_url
    )
    rows: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    for requested_field in requested_fields:
        field = normalize_requested_field(requested_field)
        fact_type = ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field)
        if not fact_type:
            continue
        dash_field = field.replace("_", "-")
        selectors = tuple(
            template.format(field=field, dash_field=dash_field)
            for template in REQUESTED_FIELD_DOM_SELECTOR_TEMPLATES
        )
        for selector in selectors:
            for node in doc.css(selector):
                if node.is_hidden():
                    continue
                value = _requested_node_value(node, fact_type)
                key = (fact_type, value.casefold())
                if not value or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    evidence(
                        bundle,
                        "html",
                        "dom",
                        fact_type,
                        value,
                        SourceLocator(
                            kind="css_selector",
                            value=selector,
                            preview=value[:120],
                        ),
                        hint=EntityHint(entity_type="product"),
                        confidence=0.62,
                        subject_id=product_subject,
                    )
                )
    return tuple(rows)


def _requested_node_value(node, fact_type: str) -> str:
    attribute_order = (
        ("href", "content", "value", "title", "aria-label")
        if fact_type == "product.url"
        else ("src", "data-src", "content", "href", "alt", "title")
        if fact_type == "asset.image_url"
        else ("content", "value", "title", "aria-label")
    )
    for attribute in attribute_order:
        value = str(node.attribute(attribute) or "").strip()
        if value:
            return value
    return " ".join(node.text().split()).strip()


def _variant_controls(
    bundle: CaptureBundle, doc, product_subject: str
) -> list[Evidence]:
    out: list[Evidence] = []
    for axis, selectors in {
        "size": (
            'select[name*="size" i] option',
            "select option",
            '[data-option-name*="size" i]',
            '[aria-label*="size" i]',
        ),
        "color": (
            'select[name*="color" i] option',
            '[data-option-name*="color" i]',
            '[aria-label*="color" i]',
        ),
    }.items():
        seen: set[str] = set()
        for selector in selectors:
            for index, tag in enumerate(doc.css(selector)):
                raw_value = str(
                    tag.attribute("value") or tag.attribute("aria-label") or tag.text()
                ).strip()
                value = _variant_value(raw_value, axis=axis)
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                subject_id = stable_id(
                    "subject", bundle.bundle_id, "product", bundle.final_url
                )
                hint = EntityHint(entity_type="product", option_values={axis: value})
                out.append(
                    evidence(
                        bundle,
                        "dom",
                        "dom",
                        f"option.{axis}",
                        value,
                        SourceLocator(
                            kind="css_selector", value=selector, preview=value[:120]
                        ),
                        group_id=f"option:dom:{axis}",
                        hint=hint,
                        confidence=0.58,
                        subject_id=subject_id,
                        parent_subject_id=None,
                    )
                )
    return out


def _variant_value(value: str, *, axis: str) -> str | None:
    normalized = " ".join(value.split()).strip()
    lowered = normalized.casefold()
    if axis == "size":
        match = re.match(VARIANT_DOM_SIZE_LABEL_PATTERN, lowered, flags=re.I)
        if match:
            return match.group("value").strip().upper()
    if (
        not normalized
        or len(normalized) > VARIANT_DOM_MAX_LABEL_LENGTH
        or lowered in {"color", "colour", "size"}
        or lowered in VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS
        or lowered in VARIANT_PLACEHOLDER_VALUES
        or any(lowered.startswith(prefix) for prefix in VARIANT_PLACEHOLDER_PREFIXES)
        or any(phrase in lowered for phrase in VARIANT_DOM_NOISE_PHRASES)
    ):
        return None
    return normalized
