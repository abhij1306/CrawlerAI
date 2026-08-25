from __future__ import annotations

import json
import logging
import re
from html import unescape
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.extraction.collectors._helpers import (
    evidence,
    html_doc,
    text_without_non_text_descendants,
)
from app.core.config.extraction_rules import (
    SELECT_CONTROL_SIGNAL_ATTRIBUTES,
    control_signal_tokens,
    has_product_option_signal,
    is_rejected_control,
    CURRENCY_SYMBOL_MAP,
    DETAIL_BRAND_DOM_SELECTORS,
    DETAIL_BRAND_DOM_VALUE_ATTRIBUTES,
    DETAIL_BRAND_VISIBLE_LABEL_PATTERN,
    DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS,
    DETAIL_DOM_AVAILABILITY_TEXT_PATTERNS,
    DETAIL_DOM_CURRENCY_CODE_PATTERN,
    DETAIL_DOM_CURRENCY_CONTEXT_PATTERN,
    DETAIL_DOM_DESCRIPTION_MIN_CHARS,
    DETAIL_DOM_DESCRIPTION_SELECTORS,
    DETAIL_DOM_IMAGE_NEGATIVE_SCOPE_TOKENS,
    DETAIL_DOM_IMAGE_POSITIVE_SCOPE_TOKENS,
    DETAIL_DOM_OFFER_CONTEXT_ANCESTOR_LIMIT,
    DETAIL_DOM_OFFER_MAX_CANDIDATES,
    DETAIL_DOM_OFFER_SELECTORS,
    DETAIL_DOM_PRICE_TEXT_PATTERN,
    DETAIL_DOM_PRODUCT_ROOT_POSITIVE_SELECTORS,
    DETAIL_DOM_PRODUCT_ROOT_SELECTORS,
    DETAIL_HIDDEN_PRODUCT_CONTENT_NEGATIVE_TOKENS,
    DETAIL_HIDDEN_PRODUCT_CONTENT_POSITIVE_TOKENS,
    DETAIL_IMAGE_SRCSET_ATTRS,
    DETAIL_IMAGE_URL_ATTRS,
    DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS,
    VARIANT_DOM_MAX_LABEL_LENGTH,
    VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR,
    VARIANT_DOM_ATTRIBUTE_JSON_ATTRIBUTE,
    VARIANT_DOM_ATTRIBUTE_URL_ATTRIBUTES,
    VARIANT_DOM_NOISE_PHRASES,
    VARIANT_DOM_SIZE_LABEL_PATTERN,
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
    VARIANT_URL_AXIS_PARAMS,
)
from app.core.config import extraction_rules as rules
from app.core.config import field_mappings
from app.core.config.field_mappings import (
    ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
    REQUESTED_FIELD_DOM_SELECTOR_TEMPLATES,
)
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.documents import HtmlNode
from app.core.shared.ids import stable_id
from app.core.records.field_policy import normalize_field_key, normalize_requested_field
from app.core.shared.url_utils import is_utility_image_url, largest_srcset_url

logger = logging.getLogger(__name__)


class DomCollector:
    collector_id = "dom"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        _, doc = html_doc(bundle, artifacts)
        product_subject = stable_id(
            "subject", bundle.bundle_id, "product", bundle.final_url
        )
        out = _base_dom_evidence(bundle, doc, product_subject)
        out.extend(_product_brand_evidence(bundle, doc, product_subject))
        product_roots = _product_root_nodes(doc)
        out.extend(
            _product_description_evidence(bundle, product_roots, product_subject)
        )
        out.extend(_product_offer_evidence(bundle, product_roots, product_subject))
        for img, confidence in _product_image_nodes(doc):
            src = _image_node_url(img)
            locator = _css_locator(img.stable_locator(), src)
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
                    parent_scope="product",
                )
            )
        out.extend(_commercial_variant_controls(bundle, doc, product_subject))
        out.extend(_variant_controls(bundle, doc, product_subject))
        return tuple(out)


def _base_dom_evidence(
    bundle: CaptureBundle, doc, product_subject: str
) -> list[Evidence]:
    rows: list[Evidence] = []
    for selector, fact in rules.DETAIL_DOM_BASE_SELECTORS:
        for tag in doc.css(selector):
            row = _base_dom_row(bundle, tag, selector, fact, product_subject)
            if row is not None:
                rows.append(row)
    return rows


def _base_dom_row(
    bundle: CaptureBundle,
    tag: HtmlNode,
    selector: str,
    fact: str,
    product_subject: str,
) -> Evidence | None:
    if _is_commercial_variant_control(tag):
        return None
    attr = next(
        (
            attribute
            for token, attribute in (
                ("price", "data-price"),
                ("currency", "data-currency"),
                ("sku", "data-sku"),
            )
            if token in selector
        ),
        None,
    )
    value = str(tag.attribute(attr) if attr else tag.text()).strip()
    if not value:
        return None
    is_offer = fact.startswith("offer.")
    group = "offer:dom:product" if is_offer else None
    return evidence(
        bundle,
        "dom",
        "dom",
        fact,
        value,
        SourceLocator(kind="css_selector", value=selector),
        group_id=group,
        hint=EntityHint(entity_type="offer" if is_offer else "product"),
        confidence=0.6,
        subject_id=group if is_offer else product_subject,
        parent_subject_id=product_subject if is_offer else None,
        parent_scope="product" if is_offer else None,
    )


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
            role = _brand_node_role(node)
            rows.append(
                _product_dom_evidence(
                    bundle,
                    "product.brand",
                    value,
                    SourceLocator(
                        kind="css_selector",
                        value=node.stable_locator(),
                        preview=value[:120],
                    ),
                    product_subject,
                    0.72,
                    metadata={
                        "brand_evidence_kind": "explicit_product_label",
                        "brand_role": role,
                    },
                )
            )
    return tuple(rows)


def _product_dom_evidence(
    bundle: CaptureBundle,
    fact_type: str,
    value: str,
    locator: SourceLocator,
    subject_id: str,
    confidence: float,
    *,
    source: str = "dom",
    flags: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> Evidence:
    return evidence(
        bundle,
        source,
        "dom",
        fact_type,
        value,
        locator,
        hint=EntityHint(entity_type="product"),
        confidence=confidence,
        flags=flags,
        subject_id=subject_id,
        metadata=metadata,
    )


def _brand_node_role(node: HtmlNode) -> str:
    context = " ".join(
        str(node.attribute(attribute) or "").casefold()
        for attribute in ("class", "id", "data-testid", "itemprop")
    )
    if "designer" in context or "designed" in context:
        return "designer"
    if "manufacturer" in context:
        return "manufacturer"
    if "vendor" in context:
        return "vendor"
    if "seller" in context:
        return "seller"
    if "retailer" in context:
        return "retailer"
    return "manufacturer"


def _brand_node_value(node: HtmlNode) -> str:
    for attribute in DETAIL_BRAND_DOM_VALUE_ATTRIBUTES:
        if value := str(node.attribute(attribute) or "").strip():
            return value
    text = " ".join(str(node.text() or "").split())
    match = re.fullmatch(DETAIL_BRAND_VISIBLE_LABEL_PATTERN, text, re.IGNORECASE)
    if match is not None:
        return str(match.group("brand") or "").strip()
    context = " ".join(
        str(node.attribute(attribute) or "").casefold()
        for attribute in ("class", "id", "data-testid", "itemprop")
    )
    if any(
        token in context for token in ("product-brand", "product_brand", "manufacturer")
    ):
        return text if 0 < len(text) <= 80 else ""
    return ""


def _product_root_nodes(doc) -> tuple[HtmlNode, ...]:
    roots: list[HtmlNode] = []
    seen: set[int] = set()
    for selector in DETAIL_DOM_PRODUCT_ROOT_SELECTORS:
        for node in doc.safe_css(selector):
            identity = node.identity()
            if identity in seen or _node_context_excluded(node):
                continue
            if not any(
                node.safe_css(positive)
                for positive in DETAIL_DOM_PRODUCT_ROOT_POSITIVE_SELECTORS
            ):
                continue
            roots.append(node)
            seen.add(identity)
    return tuple(roots)


def _product_description_evidence(
    bundle: CaptureBundle, roots: tuple[HtmlNode, ...], product_subject: str
) -> tuple[Evidence, ...]:
    rows: list[Evidence] = []
    seen: set[str] = set()
    for node in _root_selector_nodes(roots, DETAIL_DOM_DESCRIPTION_SELECTORS):
        admitted = _admit_description_node(node, seen)
        if admitted is None:
            continue
        value, hidden = admitted
        metadata: dict[str, object] = {"component_role": "product_panel"}
        if hidden:
            metadata["visibility"] = "hidden"
        rows.append(
            _product_dom_evidence(
                bundle,
                "product.description",
                value,
                _css_locator(node.stable_locator(), value),
                product_subject,
                0.66 if hidden else 0.74,
                flags=("hidden_product_content",) if hidden else (),
                metadata=metadata,
            )
        )
    return tuple(rows)


def _root_selector_nodes(
    roots: tuple[HtmlNode, ...], selectors: tuple[str, ...], limit: int | None = None
):
    return (
        node
        for root in roots
        for selector in selectors
        for node in root.safe_css(selector)[:limit]
    )


def _admit_description_node(
    node: HtmlNode,
    seen: set[str],
) -> tuple[str, bool] | None:
    hidden = node.is_hidden()
    if _node_context_excluded(node) or (
        hidden and not _hidden_product_content_allowed(node)
    ):
        return None
    value = _description_node_value(node)
    key = value.casefold()
    if not value or len(value) < DETAIL_DOM_DESCRIPTION_MIN_CHARS or key in seen:
        return None
    seen.add(key)
    return value, hidden


def _description_node_value(node: HtmlNode) -> str:
    for attribute in ("data-description", "content", "value", "title", "aria-label"):
        if value := str(node.attribute(attribute) or "").strip():
            return " ".join(value.split())
    return text_without_non_text_descendants(node)


def _product_offer_evidence(
    bundle: CaptureBundle, roots: tuple[HtmlNode, ...], product_subject: str
) -> tuple[Evidence, ...]:
    rows: list[Evidence] = []
    seen: set[tuple[str, str, str]] = set()
    for node in _root_selector_nodes(
        roots, DETAIL_DOM_OFFER_SELECTORS, DETAIL_DOM_OFFER_MAX_CANDIDATES
    ):
        offer = _admit_offer_node(node, seen)
        if offer is None:
            continue
        price, currency, availability = offer
        group = f"offer:dom:{node.identity()}"
        subject_id = stable_id("subject", bundle.bundle_id, group)
        locator = _css_locator(node.stable_locator(), price)
        for fact_type, value in (
            ("offer.price", price),
            ("offer.currency", currency),
            ("offer.availability", availability),
        ):
            if value:
                rows.append(
                    evidence(
                        bundle,
                        "dom",
                        "dom",
                        fact_type,
                        value,
                        locator,
                        group_id=group,
                        hint=EntityHint(entity_type="offer"),
                        confidence=0.7,
                        subject_id=subject_id,
                        parent_subject_id=product_subject,
                        parent_scope="product",
                        metadata={"component_role": "product_offer"},
                    )
                )
    return tuple(rows)


def _admit_offer_node(
    node: HtmlNode,
    seen: set[tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    if (
        node.is_hidden()
        or _node_context_excluded(node)
        or _is_commercial_variant_control(node)
    ):
        return None
    offer = _visible_offer_values(node)
    if offer is None or offer in seen:
        return None
    seen.add(offer)
    return offer


def _visible_offer_values(node: HtmlNode) -> tuple[str, str, str] | None:
    price_text = _offer_price_text(node)
    match = re.search(DETAIL_DOM_PRICE_TEXT_PATTERN, price_text, re.IGNORECASE)
    if match is None:
        return None
    amount = _normalize_dom_price_amount(str(match.group("amount") or ""))
    if not amount:
        return None
    currency = _offer_currency(node, match)
    availability = _offer_availability(node)
    return amount, currency, availability


def _normalize_dom_price_amount(value: str) -> str:
    amount = value.strip()
    separators = [index for index, char in enumerate(amount) if char in ",."]
    if not separators:
        return amount
    decimal_index = separators[-1]
    trailing_digits = len(amount) - decimal_index - 1
    decimal_separator = amount[decimal_index] if trailing_digits in {1, 2} else ""
    normalized = "".join(char for char in amount if char not in ",.")
    if not decimal_separator:
        return normalized
    return f"{normalized[:-trailing_digits]}.{normalized[-trailing_digits:]}"


def _offer_price_text(node: HtmlNode) -> str:
    for attribute in ("data-price", "content", "value", "aria-label", "title"):
        value = str(node.attribute(attribute) or "").strip()
        if value:
            return value
    return " ".join(node.text(separator=" ", strip=True).split())


def _offer_currency(node: HtmlNode, price_match: re.Match[str]) -> str:
    for current in (node, *node.ancestors()[:DETAIL_DOM_OFFER_CONTEXT_ANCESTOR_LIMIT]):
        for attribute in ("data-currency", "content", "aria-label", "title"):
            value = str(current.attribute(attribute) or "").strip().upper()
            if re.fullmatch(DETAIL_DOM_CURRENCY_CODE_PATTERN, value):
                return value
    code = str(price_match.group("code") or "").strip().upper()
    if code:
        return code
    symbol = str(price_match.group("symbol") or "").strip()
    if symbol:
        return CURRENCY_SYMBOL_MAP.get(symbol, "")
    context = _offer_context_text(node).upper()
    code_match = re.search(DETAIL_DOM_CURRENCY_CONTEXT_PATTERN, context)
    return code_match.group(1) if code_match else ""


def _offer_availability(node: HtmlNode) -> str:
    context = _offer_context_text(node)
    for canonical, patterns in DETAIL_DOM_AVAILABILITY_TEXT_PATTERNS.items():
        if any(re.search(pattern, context, re.IGNORECASE) for pattern in patterns):
            return canonical
    return ""


def _offer_context_text(node: HtmlNode) -> str:
    nodes = (node, *node.ancestors()[:DETAIL_DOM_OFFER_CONTEXT_ANCESTOR_LIMIT])
    return " ".join(
        " ".join(current.text(separator=" ", strip=True) for current in nodes).split()
    )


def _node_context_excluded(node: HtmlNode) -> bool:
    nodes = (node, *node.ancestors()[:8])
    context = " ".join(
        str(current.attribute(attribute) or "").casefold()
        for current in nodes
        for attribute in rules.DETAIL_DOM_IMAGE_SCOPE_ATTRIBUTES
    )
    tokens = (*DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS, *DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS)
    return any(token in context for token in tokens)


def _product_image_nodes(doc) -> tuple[tuple[HtmlNode, float], ...]:
    candidates = _product_image_candidates(doc)
    scoped = [
        node
        for node, context in candidates
        if node.attribute("data-product-image") is not None
        or any(token in context for token in DETAIL_DOM_IMAGE_POSITIVE_SCOPE_TOKENS)
    ]
    if scoped:
        return tuple((node, 0.58) for node in scoped)
    # Fail closed on galleries: a single admissible main image is a trustworthy
    # fallback, but several un-scoped candidates are usually another gallery.
    return tuple((node, 0.5) for node, _ in candidates) if len(candidates) == 1 else ()


def _product_image_candidates(doc) -> list[tuple[HtmlNode, str]]:
    candidates: list[tuple[HtmlNode, str]] = []
    seen: set[int] = set()
    for node in doc.css(rules.DETAIL_DOM_IMAGE_CANDIDATE_SELECTOR):
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
    return candidates


def _image_node_url(node: HtmlNode) -> str:
    for attribute in DETAIL_IMAGE_URL_ATTRS:
        if (
            value := str(node.attribute(attribute) or "").strip()
        ) and not is_utility_image_url(value):
            return value
    for attribute in DETAIL_IMAGE_SRCSET_ATTRS:
        if (
            value := largest_srcset_url(str(node.attribute(attribute) or ""))
        ) and not is_utility_image_url(value):
            return value
    return ""


def _css_locator(value: str, preview: str) -> SourceLocator:
    return SourceLocator(kind="css_selector", value=value, preview=preview[:120])


def _image_scope_context(node: HtmlNode) -> str:
    return " ".join(
        str(current.attribute(attribute) or "").casefold()
        for current in (node, *node.ancestors()[:12])
        for attribute in rules.DETAIL_DOM_IMAGE_SCOPE_ATTRIBUTES
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
        rows.extend(
            _requested_field_evidence(
                bundle,
                doc,
                normalize_requested_field(requested_field),
                product_subject,
                seen,
            )
        )
    return tuple(rows)


def _requested_field_evidence(
    bundle: CaptureBundle,
    doc,
    field: str,
    product_subject: str,
    seen: set[tuple[str, str]],
) -> tuple[Evidence, ...]:
    fact_type = ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field)
    if not fact_type:
        return ()
    rows: list[Evidence] = []
    dash_field = field.replace("_", "-")
    for template in REQUESTED_FIELD_DOM_SELECTOR_TEMPLATES:
        selector = template.format(field=field, dash_field=dash_field)
        for node in doc.css(selector):
            admitted = _admit_requested_node(node, fact_type, seen)
            if admitted is None:
                continue
            value, hidden = admitted
            metadata: dict[str, object] = (
                {"visibility": "hidden", "component_role": "product_panel"}
                if hidden
                else {}
            )
            rows.append(
                _product_dom_evidence(
                    bundle,
                    fact_type,
                    value,
                    _css_locator(selector, value),
                    product_subject,
                    (0.62, 0.5)[hidden],
                    source="html",
                    flags=("hidden_product_content",) if hidden else (),
                    metadata=metadata,
                )
            )
    return tuple(rows)


def _admit_requested_node(
    node: HtmlNode,
    fact_type: str,
    seen: set[tuple[str, str]],
) -> tuple[str, bool] | None:
    hidden = node.is_hidden()
    if hidden and not _hidden_product_content_allowed(node):
        return None
    value = _requested_node_value(node, fact_type)
    key = (fact_type, value.casefold())
    if not value or key in seen:
        return None
    seen.add(key)
    return value, hidden


def _hidden_product_content_allowed(node: HtmlNode) -> bool:
    raw_parts = [
        str(current.attribute(attribute) or "")
        for current in (node, *node.ancestors()[:8])
        for attribute in rules.DETAIL_DOM_IMAGE_SCOPE_ATTRIBUTES
    ]
    tokens = {
        token
        for part in raw_parts
        for token in re.split(r"[^a-z0-9]+", part.casefold())
        if token
    }
    phrases = {" ".join(part.casefold().split()) for part in raw_parts if part.strip()}
    if any(
        _hidden_product_context_matches(token, tokens=tokens, phrases=phrases)
        for token in DETAIL_HIDDEN_PRODUCT_CONTENT_NEGATIVE_TOKENS
    ):
        return False
    return any(
        _hidden_product_context_matches(token, tokens=tokens, phrases=phrases)
        for token in DETAIL_HIDDEN_PRODUCT_CONTENT_POSITIVE_TOKENS
    )


def _hidden_product_context_matches(
    token: str, *, tokens: set[str], phrases: set[str]
) -> bool:
    normalized = " ".join(str(token or "").casefold().split())
    if not normalized:
        return False
    if " " in normalized:
        return normalized in phrases
    return normalized in tokens


def _requested_node_value(node, fact_type: str) -> str:
    attribute_order = rules.DETAIL_DOM_REQUESTED_VALUE_ATTRIBUTES.get(
        fact_type, rules.DETAIL_DOM_REQUESTED_DEFAULT_VALUE_ATTRIBUTES
    )
    for attribute in attribute_order:
        value = str(node.attribute(attribute) or "").strip()
        if value:
            return value
    return " ".join(node.text().split()).strip()


def _is_commercial_variant_control(node: HtmlNode) -> bool:
    return bool(
        node.attribute("data-size")
        and node.attribute("data-sku")
        and (node.attribute("data-price") or node.attribute("data-currency"))
    )


def _commercial_variant_controls(
    bundle: CaptureBundle, doc, product_subject: str
) -> list[Evidence]:
    rows: list[Evidence] = []
    selector = "[data-size][data-sku][data-price], [data-size][data-sku][data-currency]"
    for node in doc.css(selector):
        size = _variant_value(str(node.attribute("data-size") or ""), axis="size")
        sku = str(node.attribute("data-sku") or "").strip()
        if not size or not sku:
            continue
        hint = EntityHint(entity_type="variant", sku=sku, option_values={"size": size})
        variant_subject = stable_id("subject", bundle.bundle_id, "dom", "variant", sku)
        variant_group = f"variant:dom:{sku}"
        locator = _css_locator(node.stable_locator(), size)
        variant_fields = (
            ("variant.sku", sku),
            ("variant.option.size", size),
        )
        for fact_type, value in variant_fields:
            rows.append(
                evidence(
                    bundle,
                    "dom",
                    "dom",
                    fact_type,
                    value,
                    locator,
                    group_id=variant_group,
                    hint=hint,
                    confidence=0.76,
                    subject_id=variant_subject,
                    parent_subject_id=product_subject,
                    parent_scope="product",
                )
            )
        offer_group = f"offer:dom:{sku}"
        stock = str(node.attribute("data-stock") or "").strip().casefold()
        offer_fields = (
            ("offer.price", str(node.attribute("data-price") or "").strip()),
            ("offer.currency", str(node.attribute("data-currency") or "").strip()),
            (
                "offer.availability",
                "in_stock"
                if stock in {"1", "true", "yes"}
                else "out_of_stock"
                if stock in {"0", "false", "no"}
                else "",
            ),
        )
        for fact_type, value in offer_fields:
            if not value:
                continue
            rows.append(
                evidence(
                    bundle,
                    "dom",
                    "dom",
                    fact_type,
                    value,
                    locator,
                    group_id=offer_group,
                    hint=hint,
                    confidence=0.76,
                    subject_id=stable_id("subject", bundle.bundle_id, offer_group),
                    parent_subject_id=variant_subject,
                    parent_scope="variant",
                )
            )
    return rows


def _variant_controls(
    bundle: CaptureBundle, doc, product_subject: str
) -> list[Evidence]:
    out: list[Evidence] = []
    out.extend(_attribute_variant_controls(bundle, doc, product_subject))
    seen_by_axis: dict[str, set[str]] = {"size": set(), "color": set()}
    # Select-based option axes: admit a <select>'s options only when the select
    # itself is a credible product-option control (crawl-run-95 audit). Review
    # sorters, country/quantity/pagination/address selects are rejected by
    # semantic role so they can never fabricate a size axis.
    for select in doc.css("select"):
        axis = _select_option_axis(select, doc)
        if axis is None:
            continue
        for option in select.css("option"):
            raw_value = str(
                option.attribute("value")
                or option.attribute("aria-label")
                or option.text()
            ).strip()
            _emit_option_evidence(
                out,
                bundle,
                axis,
                raw_value,
                seen_by_axis[axis],
                selector="select option",
            )
    # Non-select swatch / button controls carrying an explicit axis label.
    for axis, selectors in {
        "size": ('[data-option-name*="size" i]', '[aria-label*="size" i]'),
        "color": (
            '[data-option-name*="color" i]',
            '[data-option-name*="colour" i]',
            '[aria-label*="color" i]',
            '[aria-label*="colour" i]',
        ),
    }.items():
        for selector in selectors:
            for tag in doc.css(selector):
                if tag.tag() == "select":
                    continue
                raw_value = str(
                    tag.attribute("value") or tag.attribute("aria-label") or tag.text()
                ).strip()
                _emit_option_evidence(
                    out, bundle, axis, raw_value, seen_by_axis[axis], selector=selector
                )
    return out


def _select_option_axis(select: HtmlNode, doc: HtmlNode) -> str | None:
    """Return the product-option axis a ``<select>`` credibly represents.

    Non-product controls (sort, country, quantity, review, pagination, address)
    are rejected by semantic role; the remaining select yields an axis only when
    it (or its associated ``<label>``) explicitly names ``size`` or ``color`` —
    never a bare/opaque select.
    """
    signal_values = [
        select.attribute(attribute) for attribute in SELECT_CONTROL_SIGNAL_ATTRIBUTES
    ]
    signal_values.append(_select_label_text(select, doc))
    tokens = control_signal_tokens(signal_values)
    signal = " ".join(value for value in signal_values if value)
    if is_rejected_control(tokens, signal=signal):
        return None
    axis = (
        "size"
        if "size" in tokens
        else "color"
        if {"color", "colour"} & tokens
        else None
    )
    if axis is None or not has_product_option_signal(tokens, axis=axis):
        return None
    return axis


def _select_label_text(select: HtmlNode, doc: HtmlNode) -> str:
    """Text of the ``<label>`` bound to ``select`` (via ``for``/id or adjacency)."""
    parent = select.parent()
    if parent is not None and parent.tag() == "label":
        return parent.text()
    select_id = str(select.attribute("id") or "").strip()
    if select_id:
        label = next(iter(doc.safe_css(f"label[for={json.dumps(select_id)}]")), None)
        if label is not None:
            return label.text()
    previous = select.previous_element()
    if previous is not None and previous.tag() == "label":
        return previous.text()
    return ""


def _emit_option_evidence(
    out: list[Evidence],
    bundle: CaptureBundle,
    axis: str,
    raw_value: str,
    seen: set[str],
    *,
    selector: str,
) -> None:
    value = _variant_value(raw_value, axis=axis)
    if not value:
        return
    key = value.lower()
    if key in seen:
        return
    seen.add(key)
    subject_id = stable_id("subject", bundle.bundle_id, "product", bundle.final_url)
    hint = EntityHint(entity_type="product", option_values={axis: value})
    out.append(
        evidence(
            bundle,
            "dom",
            "dom",
            f"option.{axis}",
            value,
            SourceLocator(kind="css_selector", value=selector, preview=value[:120]),
            group_id=f"option:dom:{axis}",
            hint=hint,
            confidence=0.58,
            subject_id=subject_id,
            parent_subject_id=None,
        )
    )


def _attribute_variant_controls(
    bundle: CaptureBundle, doc, product_subject: str
) -> list[Evidence]:
    rows: list[Evidence] = []
    option_seen: set[tuple[str, str]] = set()
    variant_seen: set[str] = set()
    for node in doc.css(VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR):
        axis = _attribute_control_axis(node)
        if axis is None:
            continue
        value = _attribute_control_value(node, axis=axis)
        if value is None:
            continue
        control_url = _attribute_control_url(bundle, node)
        url_options = _variant_options_from_url(control_url) if control_url else {}
        options = {**url_options, axis: value}
        if {"color", "size"} <= set(options) and control_url:
            if control_url in variant_seen:
                continue
            variant_seen.add(control_url)
            rows.extend(
                _attribute_control_variant_rows(
                    bundle,
                    node,
                    product_subject,
                    control_url=control_url,
                    options=options,
                )
            )
            continue
        option_key = (axis, value.casefold())
        if option_key in option_seen:
            continue
        option_seen.add(option_key)
        rows.append(
            evidence(
                bundle,
                "dom",
                "dom",
                f"option.{axis}",
                value,
                SourceLocator(
                    kind="css_selector",
                    value=node.stable_locator(),
                    preview=value[:120],
                ),
                group_id=f"option:dom:{axis}",
                hint=EntityHint(entity_type="product", option_values={axis: value}),
                confidence=0.62,
                subject_id=product_subject,
                parent_subject_id=None,
            )
        )
    return rows


def _attribute_control_variant_rows(
    bundle: CaptureBundle,
    node: HtmlNode,
    product_subject: str,
    *,
    control_url: str,
    options: dict[str, str],
) -> list[Evidence]:
    variant_subject = stable_id(
        "subject", bundle.bundle_id, "dom", "variant", control_url
    )
    variant_group = f"variant:dom:{control_url}"
    hint = EntityHint(
        entity_type="variant",
        url=control_url,
        option_values=options,
        selected=_attribute_control_selected(node),
    )
    locator = _css_locator(node.stable_locator(), control_url)
    rows: list[Evidence] = []
    variant_fields: list[tuple[str, object]] = [
        ("variant.url", control_url),
        *((f"variant.option.{axis}", value) for axis, value in sorted(options.items())),
    ]
    selected = _attribute_control_selected(node)
    if selected is not None:
        variant_fields.append(("variant.selected", selected))
    for fact_type, value in variant_fields:
        rows.append(
            evidence(
                bundle,
                "dom",
                "dom",
                fact_type,
                value,
                locator,
                group_id=variant_group,
                hint=hint,
                confidence=0.74,
                subject_id=variant_subject,
                parent_subject_id=product_subject,
                parent_scope="product",
            )
        )
    availability = _attribute_control_availability(node)
    if availability:
        rows.append(
            evidence(
                bundle,
                "dom",
                "dom",
                "offer.availability",
                availability,
                locator,
                group_id=f"offer:dom:{control_url}",
                hint=hint,
                confidence=0.7,
                subject_id=stable_id(
                    "subject", bundle.bundle_id, "dom", "offer", control_url
                ),
                parent_subject_id=variant_subject,
                parent_scope="variant",
            )
        )
    return rows


def _attribute_control_axis(node: HtmlNode) -> str | None:
    raw_axis = str(node.attribute("data-attr-id") or "").strip().casefold()
    return VARIANT_URL_AXIS_PARAMS.get(raw_axis)


def _attribute_control_value(node: HtmlNode, *, axis: str) -> str | None:
    data = _attribute_control_json(node)
    raw = (
        str(node.attribute("data-attr-value") or "").strip()
        or str(node.attribute("data-dvalue") or "").strip()
        or str(data.get("displayValue") or "").strip()
        or str(data.get("value") or "").strip()
        or str(node.attribute("data-id") or "").strip()
        or " ".join(node.text().split()).strip()
    )
    return _variant_value(raw, axis=axis)


def _attribute_control_url(bundle: CaptureBundle, node: HtmlNode) -> str | None:
    data = _attribute_control_json(node)
    raw_url = (
        next(
            (
                str(node.attribute(attribute) or "").strip()
                for attribute in VARIANT_DOM_ATTRIBUTE_URL_ATTRIBUTES
                if str(node.attribute(attribute) or "").strip()
            ),
            "",
        )
        or str(data.get("url") or "").strip()
    )
    if not raw_url:
        return None
    return urljoin(bundle.final_url or bundle.requested_url, unescape(raw_url))


def _attribute_control_json(node: HtmlNode) -> dict[str, object]:
    raw = str(node.attribute(VARIANT_DOM_ATTRIBUTE_JSON_ATTRIBUTE) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(unescape(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_flag_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _attribute_control_selected(node: HtmlNode) -> bool | None:
    data = _attribute_control_json(node)
    if "selected" in data:
        return _json_flag_bool(data["selected"])
    classes = {part.casefold() for part in str(node.attribute("class") or "").split()}
    if classes & {"selected", "active", "is-selected"}:
        return True
    return None


def _attribute_control_availability(node: HtmlNode) -> str | None:
    data = _attribute_control_json(node)
    if "selectable" in data:
        return "in_stock" if _json_flag_bool(data["selectable"]) else "out_of_stock"
    if node.attribute("disabled") is not None:
        return "out_of_stock"
    return None


def _variant_options_from_url(url: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=False):
        axis_match = re.match(VARIANT_DOM_URL_AXIS_PARAM_PATTERN, key, flags=re.I)
        if not axis_match:
            continue
        axis = VARIANT_URL_AXIS_PARAMS.get(axis_match.group("axis").casefold())
        if not axis:
            continue
        parsed_value = _variant_value(value, axis=axis)
        if parsed_value:
            options[axis] = parsed_value
    return options


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


def css_recipe_evidence(bundle, reader) -> tuple[Evidence, ...]:
    rules_ref = next(
        (ref for ref in bundle.artifacts if ref.artifact_id == "css_field_rules"), None
    )
    rules = reader.read_json(rules_ref) if rules_ref is not None else []
    if not isinstance(rules, list):
        return ()
    doc = reader.document_store.html("html")
    product_subject_id = stable_id(
        "subject", bundle.bundle_id, "product", bundle.final_url
    )
    rows: list[Evidence] = []
    for row in rules:
        binding = _css_rule_binding(row)
        if binding is None:
            continue
        selector, fact_type = binding
        try:
            nodes = doc.css(selector)
        except Exception:
            logger.debug(
                "Requested-field selector %r failed; skipping it",
                selector,
                exc_info=True,
            )
            continue
        for node in nodes[:3]:
            evidence_row = _css_rule_node_evidence(
                bundle,
                node,
                selector=selector,
                fact_type=fact_type,
                product_subject_id=product_subject_id,
            )
            if evidence_row is not None:
                rows.append(evidence_row)
    return tuple(rows)


def _css_rule_binding(row: object) -> tuple[str, str] | None:
    if not isinstance(row, dict) or not bool(row.get("is_active", True)):
        return None
    selector = str(row.get("css_selector") or "").strip()
    fact_type = field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(
        normalize_field_key(str(row.get("field_name") or ""))
    )
    return (selector, fact_type) if selector and fact_type else None


def _css_rule_node_evidence(
    bundle,
    node: HtmlNode,
    *,
    selector: str,
    fact_type: str,
    product_subject_id: str,
) -> Evidence | None:
    if node.is_hidden():
        return None
    value = _css_node_value(node, fact_type)
    if value in (None, "", [], {}):
        return None
    hint, subject_id, parent_subject_id, group_id = _css_subject_binding(
        bundle,
        fact_type=fact_type,
        value=value,
        product_subject_id=product_subject_id,
    )
    return evidence(
        bundle,
        "css_field_rules",
        "css_recipe",
        fact_type,
        value,
        SourceLocator(kind="css_selector", value=selector, preview=str(value)[:120]),
        hint=hint,
        group_id=group_id,
        confidence=0.86,
        directness="direct",
        subject_id=subject_id,
        parent_subject_id=parent_subject_id,
    )


def _css_subject_binding(
    bundle,
    *,
    fact_type: str,
    value: object,
    product_subject_id: str,
) -> tuple[EntityHint, str, str | None, str]:
    if fact_type.startswith("offer."):
        return (
            EntityHint(entity_type="offer", url=bundle.final_url),
            stable_id("subject", bundle.bundle_id, "offer", bundle.final_url),
            product_subject_id,
            "offer",
        )
    if fact_type.startswith("asset."):
        return (
            EntityHint(entity_type="asset", url=bundle.final_url),
            stable_id("subject", bundle.bundle_id, "asset", value),
            product_subject_id,
            "asset",
        )
    return EntityHint(entity_type="product"), product_subject_id, None, "product"


def _css_node_value(node, fact_type: str) -> str | None:
    attr_order = rules.DETAIL_DOM_REQUESTED_VALUE_ATTRIBUTES.get(
        fact_type, rules.DETAIL_DOM_REQUESTED_DEFAULT_VALUE_ATTRIBUTES
    )
    for attr in attr_order:
        value = str(node.attribute(attr) or "").strip()
        if value:
            return value
    return re.sub(r"\s+", " ", node.text(separator=" ", strip=True)).strip() or None
