from __future__ import annotations

import json
import re

from app.core.config.extraction_rules import (
    SELECT_CONTROL_SIGNAL_ATTRIBUTES,
    VARIANT_DOM_ATTRIBUTE_JSON_ATTRIBUTE,
    VARIANT_DOM_IDENTIFIER_CONTROL_SELECTOR,
    VARIANT_DOM_MAX_LABEL_LENGTH,
    VARIANT_DOM_NOISE_PHRASES,
    VARIANT_DOM_SELECTION_AXISLESS_ROLES,
    VARIANT_DOM_SELECTION_CONTEXT_ANCESTOR_LIMIT,
    VARIANT_DOM_SELECTION_CONTEXT_ROLES,
    VARIANT_DOM_SELECTION_CONTROL_SELECTOR,
    VARIANT_DOM_SELECTION_SIGNAL_METADATA_KEY,
    VARIANT_DOM_SELECTION_SOURCE_METADATA_KEY,
    VARIANT_DOM_SELECTION_STANDARD_CONFIDENCE,
    VARIANT_DOM_SELECTION_STANDARD_SOURCE,
    VARIANT_DOM_SELECTION_VALUE_ATTRIBUTES,
    VARIANT_DOM_SELECTION_VALUE_METADATA_KEY,
    VARIANT_DOM_SELECTION_VALUE_PREFIX_PATTERN,
    VARIANT_DOM_SELECTION_VALUE_SUFFIX_PATTERN,
    VARIANT_DOM_SELECTION_VENDOR_CONFIDENCE,
    VARIANT_DOM_SELECTION_VENDOR_SOURCE,
    VARIANT_DOM_SIZE_LABEL_PATTERN,
    VARIANT_OPTION_CONTROL_SCAN_LIMIT,
    VARIANT_OPTION_FLAG_FALSE_VALUES,
    VARIANT_OPTION_SELECTED_CLASS_TOKENS,
    VARIANT_OPTION_SELECTED_TRUTHY_ATTRIBUTES,
    VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
    control_signal_tokens,
    has_product_option_signal,
    is_rejected_control,
)
from app.core.shared.ids import stable_id
from app.extraction.collectors._helpers import evidence
from app.extraction.collectors.dom_scoping import (
    node_context_excluded,
    node_within_roots,
)
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.documents import HtmlDocument, HtmlNode


def collect_dom_variant_identifiers(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
    product_subject: str,
) -> tuple[tuple[Evidence, ...], frozenset[int]]:
    if not roots or not doc.css("[data-sku]"):
        return (), frozenset()
    controls = doc.css(VARIANT_DOM_IDENTIFIER_CONTROL_SELECTOR)
    root_ids = {root.identity() for root in roots}
    rows: list[Evidence] = []
    seen: set[tuple[int, str]] = set()
    for node in controls:
        sku = str(node.attribute("data-sku") or "").strip()
        key = (node.identity(), sku)
        if (
            not sku
            or key in seen
            or is_commercial_variant_control(node)
            or not node_within_roots(node, root_ids)
            or node_context_excluded(node)
        ):
            continue
        seen.add(key)
        rows.append(_identifier_evidence(bundle, node, product_subject, sku))
    return tuple(rows), frozenset(node.identity() for node in controls)


def collect_commercial_variant_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
    product_subject: str,
) -> list[Evidence]:
    if not roots:
        return []
    rows: list[Evidence] = []
    root_ids = {root.identity() for root in roots}
    selector = "[data-size][data-sku][data-price], [data-size][data-sku][data-currency]"
    for node in doc.css(selector):
        if not node_within_roots(node, root_ids) or node_context_excluded(node):
            continue
        size = dom_variant_value(str(node.attribute("data-size") or ""), axis="size")
        sku = str(node.attribute("data-sku") or "").strip()
        if not size or not sku:
            continue
        rows.extend(_commercial_variant_rows(bundle, node, product_subject, sku, size))
    return rows


def collect_dom_selection_signals(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
    product_subject: str,
) -> list[Evidence]:
    if not roots:
        return []
    rows: list[Evidence] = []
    root_ids = {root.identity() for root in roots}
    for node in doc.css(VARIANT_DOM_SELECTION_CONTROL_SELECTOR)[
        :VARIANT_OPTION_CONTROL_SCAN_LIMIT
    ]:
        if not node_within_roots(node, root_ids) or node_context_excluded(node):
            continue
        selected = _selected_state(node)
        if selected is None:
            continue
        state, source = selected
        axis = option_control_axis(node, doc)
        value = _selected_control_value(node, axis=axis or "")
        if value is None or (axis is None and not _supports_axis_inference(node)):
            continue
        rows.extend(
            _selection_signal_rows(
                bundle,
                node,
                product_subject,
                axis=axis,
                value=value,
                state=state,
                source=source,
            )
        )
    return rows


def select_option_axis(select: HtmlNode, doc: HtmlDocument) -> str | None:
    signal_values = [
        select.attribute(attribute) for attribute in SELECT_CONTROL_SIGNAL_ATTRIBUTES
    ]
    signal_values.append(_select_label_text(select, doc))
    return _axis_from_signals(signal_values)


def option_control_axis(node: HtmlNode, doc: HtmlDocument) -> str | None:
    if node.tag() == "option":
        parent = node.parent()
        if parent is not None and parent.tag() == "select":
            return select_option_axis(parent, doc)
    signal_values = [
        node.attribute(attribute) for attribute in SELECT_CONTROL_SIGNAL_ATTRIBUTES
    ]
    signal_values.extend(_control_context_signals(node))
    return _axis_from_signals(signal_values)


def is_commercial_variant_control(node: HtmlNode) -> bool:
    return bool(
        node.attribute("data-size")
        and node.attribute("data-sku")
        and (node.attribute("data-price") or node.attribute("data-currency"))
    )


def dom_variant_value(value: str, *, axis: str) -> str | None:
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


def _axis_from_signals(values: list[str | None]) -> str | None:
    tokens = control_signal_tokens(values)
    signal = " ".join(value for value in values if value)
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


def _control_context_signals(node: HtmlNode) -> list[str | None]:
    values: list[str | None] = []
    for ancestor in node.ancestors()[:VARIANT_DOM_SELECTION_CONTEXT_ANCESTOR_LIMIT]:
        role = str(ancestor.attribute("role") or "").strip().casefold()
        if ancestor.tag() not in {"fieldset", "label"} and (
            role not in VARIANT_DOM_SELECTION_CONTEXT_ROLES
        ):
            continue
        values.extend(
            ancestor.attribute(attribute)
            for attribute in SELECT_CONTROL_SIGNAL_ATTRIBUTES
        )
        if ancestor.tag() == "label":
            values.append(ancestor.direct_text())
        elif ancestor.tag() == "fieldset":
            legend = ancestor.css_first("legend")
            values.append(legend.text() if legend is not None else None)
    return values


def _select_label_text(select: HtmlNode, doc: HtmlDocument) -> str:
    parent = select.parent()
    if parent is not None and parent.tag() == "label":
        return parent.text()
    select_id = str(select.attribute("id") or "").strip()
    if select_id:
        label = next(iter(doc.safe_css(f"label[for={json.dumps(select_id)}]")), None)
        if label is not None:
            return label.text()
    previous = select.previous_element()
    return previous.text() if previous is not None and previous.tag() == "label" else ""


def _selected_state(node: HtmlNode) -> tuple[bool, str] | None:
    standard_states = [
        _explicit_state(node.attribute(attribute))
        for attribute in VARIANT_OPTION_SELECTED_TRUTHY_ATTRIBUTES
        if node.attribute(attribute) is not None
    ]
    if node.tag() == "option" and node.attribute("selected") is not None:
        standard_states.append(True)
    if node.tag() == "input" and node.attribute("checked") is not None:
        standard_states.append(True)
    if standard_states:
        states = set(standard_states)
        return (
            (next(iter(states)), VARIANT_DOM_SELECTION_STANDARD_SOURCE)
            if len(states) == 1
            else None
        )
    vendor_state = _vendor_selected_state(node)
    return (
        (vendor_state, VARIANT_DOM_SELECTION_VENDOR_SOURCE)
        if vendor_state is not None
        else None
    )


def _explicit_state(value: str | None) -> bool:
    return str(value or "").strip().casefold() not in VARIANT_OPTION_FLAG_FALSE_VALUES


def _vendor_selected_state(node: HtmlNode) -> bool | None:
    raw_json = str(node.attribute(VARIANT_DOM_ATTRIBUTE_JSON_ATTRIBUTE) or "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "selected" in data:
            return _explicit_state(str(data["selected"]))
    if node.attribute("data-selected") is not None:
        return _explicit_state(node.attribute("data-selected"))
    classes = {part.casefold() for part in str(node.attribute("class") or "").split()}
    return True if classes & set(VARIANT_OPTION_SELECTED_CLASS_TOKENS) else None


def _selected_control_value(node: HtmlNode, *, axis: str) -> str | None:
    raw = next(
        (
            value
            for attribute in VARIANT_DOM_SELECTION_VALUE_ATTRIBUTES
            if (value := str(node.attribute(attribute) or "").strip())
        ),
        "",
    )
    if not raw:
        raw = " ".join(node.text().split()).strip()
    if axis == "size":
        size = dom_variant_value(raw, axis=axis)
        if size is None or size != raw:
            return size
    raw = re.sub(VARIANT_DOM_SELECTION_VALUE_PREFIX_PATTERN, "", raw, flags=re.I)
    raw = re.sub(VARIANT_DOM_SELECTION_VALUE_SUFFIX_PATTERN, "", raw, flags=re.I)
    return dom_variant_value(raw, axis=axis)


def _selection_signal_rows(
    bundle: CaptureBundle,
    node: HtmlNode,
    product_subject: str,
    *,
    axis: str | None,
    value: str,
    state: bool,
    source: str,
) -> list[Evidence]:
    subject = stable_id(
        "subject", bundle.bundle_id, "dom", "selection", node.dom_path()
    )
    group = f"variant:dom:selection:{subject}"
    hint = EntityHint(
        entity_type="variant",
        option_values={axis: value} if axis else {},
        selected=state,
    )
    metadata = {
        VARIANT_DOM_SELECTION_SIGNAL_METADATA_KEY: True,
        VARIANT_DOM_SELECTION_SOURCE_METADATA_KEY: source,
        VARIANT_DOM_SELECTION_VALUE_METADATA_KEY: value,
    }
    confidence = (
        VARIANT_DOM_SELECTION_STANDARD_CONFIDENCE
        if source == VARIANT_DOM_SELECTION_STANDARD_SOURCE
        else VARIANT_DOM_SELECTION_VENDOR_CONFIDENCE
    )
    locator = SourceLocator(kind="dom_path", value=node.dom_path(), preview=value[:120])
    common = {
        "group_id": group,
        "hint": hint,
        "confidence": confidence,
        "subject_id": subject,
        "parent_subject_id": product_subject,
        "parent_scope": "product",
        "metadata": metadata,
    }
    rows = [
        evidence(
            bundle,
            "dom",
            "dom",
            "variant.selected",
            state,
            locator,
            **common,
        ),
    ]
    if axis is not None:
        rows.append(
            evidence(
                bundle,
                "dom",
                "dom",
                f"variant.option.{axis}",
                value,
                locator,
                **common,
            )
        )
    return rows


def _supports_axis_inference(node: HtmlNode) -> bool:
    role = str(node.attribute("role") or "").strip().casefold()
    return (
        role in VARIANT_DOM_SELECTION_AXISLESS_ROLES
        or node.tag() == "option"
        or node.tag() == "input"
        and str(node.attribute("type") or "").casefold() in {"checkbox", "radio"}
    )


def _identifier_evidence(
    bundle: CaptureBundle,
    node: HtmlNode,
    product_subject: str,
    sku: str,
) -> Evidence:
    variant_subject = stable_id("subject", bundle.bundle_id, "dom", "variant", sku)
    return evidence(
        bundle,
        "dom",
        "dom",
        "variant.sku",
        sku,
        _locator(node, sku),
        group_id=f"variant:dom:{sku}",
        hint=EntityHint(entity_type="variant", sku=sku),
        confidence=0.64,
        subject_id=variant_subject,
        parent_subject_id=product_subject,
        parent_scope="product",
    )


def _commercial_variant_rows(
    bundle: CaptureBundle,
    node: HtmlNode,
    product_subject: str,
    sku: str,
    size: str,
) -> list[Evidence]:
    hint = EntityHint(entity_type="variant", sku=sku, option_values={"size": size})
    variant_subject = stable_id("subject", bundle.bundle_id, "dom", "variant", sku)
    locator = _locator(node, size)
    rows = [
        evidence(
            bundle,
            "dom",
            "dom",
            fact_type,
            value,
            locator,
            group_id=f"variant:dom:{sku}",
            hint=hint,
            confidence=0.76,
            subject_id=variant_subject,
            parent_subject_id=product_subject,
            parent_scope="product",
        )
        for fact_type, value in (("variant.sku", sku), ("variant.option.size", size))
    ]
    stock = str(node.attribute("data-stock") or "").strip().casefold()
    offer_fields = (
        ("offer.price", str(node.attribute("data-price") or "").strip()),
        ("offer.currency", str(node.attribute("data-currency") or "").strip()),
        ("offer.availability", _stock_availability(stock)),
    )
    for fact_type, value in offer_fields:
        if value:
            rows.append(
                evidence(
                    bundle,
                    "dom",
                    "dom",
                    fact_type,
                    value,
                    locator,
                    group_id=f"offer:dom:{sku}",
                    hint=hint,
                    confidence=0.76,
                    subject_id=stable_id(
                        "subject", bundle.bundle_id, f"offer:dom:{sku}"
                    ),
                    parent_subject_id=variant_subject,
                    parent_scope="variant",
                )
            )
    return rows


def _stock_availability(stock: str) -> str:
    if stock in {"1", "true", "yes"}:
        return "in_stock"
    if stock in {"0", "false", "no"}:
        return "out_of_stock"
    return ""


def _locator(node: HtmlNode, preview: str) -> SourceLocator:
    return SourceLocator(
        kind="css_selector",
        value=node.stable_locator(),
        preview=preview[:120],
    )
