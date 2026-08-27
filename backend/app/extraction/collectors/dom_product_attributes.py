from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config.extraction_rules import (
    DETAIL_DOM_DESCRIPTION_SELECTORS,
    DETAIL_DOM_MATERIAL_COMPONENT_PATTERN,
    DETAIL_DOM_MATERIAL_CONSTRUCTION_PATTERNS,
    DETAIL_DOM_MATERIAL_EXPLICIT_SELECTOR,
    DETAIL_DOM_MATERIAL_INLINE_LABEL_PATTERN,
    DETAIL_DOM_MATERIAL_INLINE_COMPOSITION_PATTERN,
    DETAIL_DOM_MATERIAL_LABEL_PATTERN,
    DETAIL_DOM_MATERIAL_MAX_VALUE_CHARS,
    DETAIL_DOM_MATERIAL_META_SELECTOR,
    DETAIL_DOM_MATERIAL_PERCENTAGE_PATTERNS,
    DETAIL_DOM_MATERIAL_SCAN_LIMIT,
    DETAIL_DOM_MATERIAL_TEXT_BLOCK_SELECTOR,
    DETAIL_DOM_MATERIAL_VALUE_BOUNDARY_PATTERN,
    DETAIL_DOM_MATERIAL_VALUE_REJECT,
    DETAIL_DOM_MATERIAL_DECORATIVE_SYMBOL_PATTERN,
)
from app.extraction.collectors._helpers import evidence
from app.extraction.collectors.dom_scoping import (
    node_context_excluded,
    node_within_roots,
)
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator
from app.extraction.documents import HtmlDocument, HtmlNode


@dataclass(frozen=True)
class _MaterialCandidate:
    value: str
    node: HtmlNode
    confidence: float
    strategy: str


def collect_product_material_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
    product_subject: str,
) -> tuple[Evidence, ...]:
    if not roots:
        return ()
    candidates = [
        *_explicit_material_candidates(doc, roots),
        *_description_material_candidates(doc, roots),
        *_metadata_material_candidates(doc),
    ]
    preferred: dict[str, _MaterialCandidate] = {}
    for candidate in candidates:
        key = candidate.value.casefold()
        current = preferred.get(key)
        if current is None or candidate.confidence > current.confidence:
            preferred[key] = candidate
    return tuple(
        _material_evidence(bundle, product_subject, candidate)
        for candidate in preferred.values()
    )


def _explicit_material_candidates(
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
) -> list[_MaterialCandidate]:
    candidates: list[_MaterialCandidate] = []
    admitted = 0
    root_ids = {root.identity() for root in roots}
    for node in doc.safe_css(DETAIL_DOM_MATERIAL_EXPLICIT_SELECTOR):
        if not node_within_roots(node, root_ids) or node_context_excluded(node):
            continue
        admitted += 1
        if admitted > DETAIL_DOM_MATERIAL_SCAN_LIMIT:
            break
        value = _explicit_material_value(node)
        if value:
            confidence = 0.86 if len(value) <= 80 else 0.82
            candidates.append(_MaterialCandidate(value, node, confidence, "label"))
    return candidates


def _description_material_candidates(
    doc: HtmlDocument,
    roots: tuple[HtmlNode, ...],
) -> list[_MaterialCandidate]:
    candidates: list[_MaterialCandidate] = []
    seen_nodes: set[int] = set()
    root_ids = {root.identity() for root in roots}
    sections = doc.safe_css(", ".join(DETAIL_DOM_DESCRIPTION_SELECTORS))
    for section in sections:
        if not node_within_roots(section, root_ids) or node_context_excluded(section):
            continue
        nodes = (section, *section.safe_css(DETAIL_DOM_MATERIAL_TEXT_BLOCK_SELECTOR))
        for node in nodes:
            if len(seen_nodes) >= DETAIL_DOM_MATERIAL_SCAN_LIMIT:
                return candidates
            if node.identity() in seen_nodes or node_context_excluded(node):
                continue
            seen_nodes.add(node.identity())
            candidates.extend(_prose_candidates(node, metadata=False))
    return candidates


def _metadata_material_candidates(doc: HtmlDocument) -> list[_MaterialCandidate]:
    candidates: list[_MaterialCandidate] = []
    for node in doc.safe_css(DETAIL_DOM_MATERIAL_META_SELECTOR):
        candidates.extend(_prose_candidates(node, metadata=True))
    return candidates


def _explicit_material_value(node: HtmlNode) -> str:
    matched_label = False
    for text in (_text(node.direct_text()), _text(node.text())):
        match = re.match(DETAIL_DOM_MATERIAL_LABEL_PATTERN, text, re.I)
        if match is None:
            continue
        matched_label = True
        if value := _clean_value(match.group("value")):
            return value
    parent = node.parent()
    if parent is not None:
        match = re.match(DETAIL_DOM_MATERIAL_LABEL_PATTERN, _text(parent.text()), re.I)
        if match is not None:
            matched_label = True
            if value := _clean_value(match.group("value")):
                return value
    if not matched_label:
        return ""
    for sibling in node.following_siblings()[:2]:
        if value := _clean_value(sibling.text()):
            return value
    return ""


def _prose_candidates(node: HtmlNode, *, metadata: bool) -> list[_MaterialCandidate]:
    text = _text(node.attribute("content") if metadata else node.text())
    if not text:
        return []
    offset = 0.08 if metadata else 0.0
    values: list[tuple[str, float, str]] = []
    inline = re.search(DETAIL_DOM_MATERIAL_INLINE_LABEL_PATTERN, text, re.I)
    if inline and (value := _clean_value(inline.group("value"))):
        values.append((value, 0.82 - offset, "inline_label"))
    composition = re.search(DETAIL_DOM_MATERIAL_INLINE_COMPOSITION_PATTERN, text, re.I)
    if composition and (value := _clean_value(composition.group("value"))):
        values.append((value, 0.82 - offset, "inline_composition"))
    percentages = _pattern_values(text, DETAIL_DOM_MATERIAL_PERCENTAGE_PATTERNS)
    if percentages:
        values.append(("; ".join(percentages), 0.76 - offset, "composition"))
    for pattern in DETAIL_DOM_MATERIAL_CONSTRUCTION_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            if value := _clean_value(match.group("value")):
                values.append((value, 0.7 - offset, "construction"))
    components = _component_values(text)
    if components:
        joined = "; ".join(components)
        if len(joined) <= DETAIL_DOM_MATERIAL_MAX_VALUE_CHARS:
            confidence = 0.7 + 0.01 * min(len(components), 4) - offset
            values.append((joined, confidence, "component"))
    return [
        _MaterialCandidate(value, node, confidence, strategy)
        for value, confidence, strategy in values
    ]


def _pattern_values(text: str, patterns: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            if value := _clean_value(match.group(0)):
                values.append(value)
    return list(dict.fromkeys(values))


def _component_values(text: str) -> list[str]:
    values = []
    for match in re.finditer(DETAIL_DOM_MATERIAL_COMPONENT_PATTERN, text, re.I):
        raw = re.sub(
            r"^.*\b(?:crafted|made|built|finished|detailed)\s+(?:from|of|with)?\s*",
            "",
            match.group(0),
            flags=re.I,
        ).strip()
        raw = re.sub(r"^(?:and|with|a|an|the|our|its)\s+", "", raw, flags=re.I)
        if value := _clean_value(raw):
            values.append(value)
    return list(dict.fromkeys(values))


def _clean_value(value: object) -> str:
    text = _text(value)
    text = re.sub(DETAIL_DOM_MATERIAL_DECORATIVE_SYMBOL_PATTERN, "", text)
    text = re.sub(DETAIL_DOM_MATERIAL_VALUE_BOUNDARY_PATTERN, "", text, flags=re.I)
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.I)
    text = text.strip(" ,.;:-")
    if (
        not text
        or len(text) > DETAIL_DOM_MATERIAL_MAX_VALUE_CHARS
        or text.casefold() in DETAIL_DOM_MATERIAL_VALUE_REJECT
    ):
        return ""
    return text


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _material_evidence(
    bundle: CaptureBundle, product_subject: str, candidate: _MaterialCandidate
) -> Evidence:
    return evidence(
        bundle,
        "html",
        "dom",
        "product.material",
        candidate.value,
        SourceLocator(
            kind="css_selector",
            value=candidate.node.stable_locator(),
            preview=candidate.value[:120],
        ),
        hint=EntityHint(entity_type="product"),
        confidence=candidate.confidence,
        subject_id=product_subject,
        subject_scope="product",
        metadata={
            "component_role": "product_details",
            "material_strategy": candidate.strategy,
        },
    )
