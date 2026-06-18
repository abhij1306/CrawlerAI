"""Reconcile extracted variant rows against rendered-DOM availability cues.

This closes a cross-tier gap that affects most ecommerce PDPs, not one site:
platform adapters and structured-data tiers (JSON-LD, Nike `__NEXT_DATA__`,
Belk RSC, Shopify, ...) frequently either report every listed variant as
available or only enumerate the in-stock variants, because real per-SKU stock is
resolved client-side after page load. On those pages the rendered DOM is the only
source of truth for per-variant stock: out-of-stock options carry a `disabled` /
`aria-disabled` / `data-disabled` control or an OOS class/flag.

`reconcile_variant_availability_from_dom` runs in finalization for every
ecommerce detail record that has variants and a rendered DOM. It:

1. Matches existing variant rows to their rendered option control (scoped to
   variant containers only, so disabled page chrome such as nav arrows or
   review/feedback buttons is never read as a variant).
2. Applies the DOM availability signal onto matched rows (downgrading an
   optimistic/empty value to `out_of_stock`, or filling a missing value with the
   DOM signal). It never upgrades a deterministic `out_of_stock`.
3. Upgrades a matched row's axis value to the richer rendered label when the
   structured tier only carried a short option token (e.g. JSON-LD `size="5"`
   vs the rendered `M 5 / W 6.5`).
4. Appends DOM-discovered out-of-stock options that the structured tier omitted
   entirely (the common "only in-stock options are listed" case).

It is identity-preserving: it does not rebuild, reorder, or strip existing rows;
it only updates the axis/availability/stock_quantity slots and appends new OOS
rows.
"""

from __future__ import annotations

__all__ = ("reconcile_variant_availability_from_dom",)

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    AVAILABILITY_IN_STOCK,
    AVAILABILITY_OUT_OF_STOCK,
    VARIANT_OPTION_CONTROL_KEY_ATTRIBUTES,
    VARIANT_OPTION_CONTROL_SCAN_LIMIT,
    VARIANT_OPTION_CONTROL_SELECTOR,
)
from app.services.extract.detail.variants.dom_options import (
    variant_option_availability,
)
from app.services.extract.variant_dom_cues import variant_scope_roots
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    public_variant_axis_fields,
)
from app.services.shared.field_coerce import clean_text, text_or_none

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_PUBLIC_AXIS_FIELDS = tuple(public_variant_axis_fields or ())
# Variant-row fields whose values can join to a DOM option control key.
_ROW_KEY_FIELDS = ("sku", "variant_id", "barcode", *_PUBLIC_AXIS_FIELDS)
_MAX_AXIS_LABEL_LEN = 40


def _normalized_key(value: object) -> str:
    text = text_or_none(value)
    if not text:
        return ""
    return _NON_ALNUM_RE.sub("", text.casefold())


def _option_control_label(
    control: Any, label_map: dict[str, Any] | None = None
) -> Any | None:
    """Resolve the <label> associated with a radio/checkbox control."""
    if not hasattr(control, "get"):
        return None
    control_id = text_or_none(control.get("id"))
    if control_id:
        label = (label_map or {}).get(control_id)
        if label is not None:
            return label
    if hasattr(control, "find_parent"):
        label = control.find_parent("label")
        if label is not None:
            return label
    parent = getattr(control, "parent", None)
    if parent is not None and hasattr(parent, "find"):
        label = parent.find("label")
        if label is not None:
            return label
    return None


def _label_map(soup: BeautifulSoup) -> dict[str, Any]:
    labels: dict[str, Any] = {}
    if not hasattr(soup, "find_all"):
        return labels
    for label in soup.find_all(
        "label", attrs={"for": True}, limit=VARIANT_OPTION_CONTROL_SCAN_LIMIT
    ):
        control_id = text_or_none(label.get("for")) if hasattr(label, "get") else None
        if control_id and control_id not in labels:
            labels[control_id] = label
    return labels


class _DomOption:
    __slots__ = ("availability", "stock_quantity", "display", "keys", "axis_key")

    def __init__(
        self,
        availability: str,
        stock_quantity: int | None,
        display: str,
        keys: set[str],
        axis_key: str | None,
    ) -> None:
        self.availability = availability
        self.stock_quantity = stock_quantity
        self.display = display
        self.keys = keys
        self.axis_key = axis_key


def _control_display_label(control: Any, label: Any | None) -> str:
    """Human-facing option label, preferring the visible <label> text."""
    selected_option = _selected_option_node(control)
    candidates: list[str] = []
    if selected_option is not None and hasattr(selected_option, "get_text"):
        candidates.append(selected_option.get_text(" ", strip=True))
    if label is not None and hasattr(label, "get_text"):
        candidates.append(label.get_text(" ", strip=True))
    if hasattr(control, "get"):
        candidates.append(str(control.get("aria-label") or ""))
    if hasattr(control, "get_text"):
        candidates.append(control.get_text(" ", strip=True))
    if hasattr(control, "get"):
        for attr_name in ("data-size", "data-value", "value", "title"):
            candidates.append(str(control.get(attr_name) or ""))
    for value in candidates:
        cleaned = _clean_dom_option_display_label(value)
        if cleaned and len(cleaned) <= _MAX_AXIS_LABEL_LEN:
            return cleaned
    return ""


def _selected_option_node(control: Any) -> Any | None:
    node = control
    if getattr(node, "name", None) == "option":
        return node
    if getattr(node, "name", None) != "select" or not hasattr(node, "find_all"):
        return None
    options = list(node.find_all("option", limit=VARIANT_OPTION_CONTROL_SCAN_LIMIT))
    selected = next((option for option in options if option.has_attr("selected")), None)
    if selected is not None:
        return selected
    value = text_or_none(node.get("value")) if hasattr(node, "get") else None
    if value:
        return next(
            (
                option
                for option in options
                if text_or_none(option.get("value")) == value
            ),
            None,
        )
    return options[0] if options else None


def _clean_dom_option_display_label(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    match = re.fullmatch(
        r"(?:choose|select|view)\s+(?:alternate\s+product\s+)?(?:colour|color)?\s*(.+?)\s+(?:variant|selected|unselected)",
        cleaned,
        flags=re.I,
    )
    if match:
        return clean_text(match.group(1))
    return cleaned


def _control_join_keys(control: Any, label: Any | None) -> set[str]:
    keys: set[str] = set()
    if hasattr(control, "get"):
        for attr_name in VARIANT_OPTION_CONTROL_KEY_ATTRIBUTES:
            raw = control.get(attr_name)
            if isinstance(raw, list):
                raw = " ".join(str(item) for item in raw if item)
            normalized = _normalized_key(raw)
            if normalized:
                keys.add(normalized)
            text = text_or_none(raw)
            if text and "_" in text:
                # `10512_33x32`-style composite values carry the bare option
                # token (`33x32`) after the separator.
                tail = _normalized_key(text.rsplit("_", 1)[-1])
                if tail:
                    keys.add(tail)
    for node in (control, label):
        if node is None or not hasattr(node, "get_text"):
            continue
        normalized = _normalized_key(node.get_text(" ", strip=True))
        if normalized:
            keys.add(normalized)
    selected_option = _selected_option_node(control)
    if selected_option is not None:
        for value in (
            selected_option.get_text(" ", strip=True)
            if hasattr(selected_option, "get_text")
            else "",
            selected_option.get("value") if hasattr(selected_option, "get") else "",
        ):
            normalized = _normalized_key(value)
            if normalized:
                keys.add(normalized)
    return keys


def _control_axis_key(control: Any, label_map: dict[str, Any]) -> str | None:
    parent = getattr(control, "parent", None)
    select_node = control if getattr(control, "name", None) == "select" else parent
    axis_labels: list[object] = []
    if select_node is not None and getattr(select_node, "name", None) == "select":
        axis_labels.extend(
            (
                select_node.get("name"),
                select_node.get("aria-label"),
                select_node.get("id"),
            )
        )
        select_id = text_or_none(select_node.get("id"))
        if select_id and select_id in label_map:
            axis_labels.append(label_map[select_id].get_text(" ", strip=True))
    for value in axis_labels:
        axis_key = normalized_variant_axis_key(value)
        if axis_key:
            return axis_key
    return None


def _collect_dom_options(soup: BeautifulSoup) -> list[_DomOption]:
    # Scope option scanning to variant containers only so disabled page chrome
    # (nav arrows, review/feedback buttons, ...) is never read as a variant.
    scope_roots = variant_scope_roots(soup)
    if not scope_roots:
        return []
    selector = str(VARIANT_OPTION_CONTROL_SELECTOR)
    options: list[_DomOption] = []
    seen_control_ids: set[int] = set()
    label_map = _label_map(soup)
    for root in scope_roots:
        if not hasattr(root, "select"):
            continue
        try:
            controls = root.select(selector)
        except Exception:
            controls = []
        for control in controls:
            if id(control) in seen_control_ids:
                continue
            if len(seen_control_ids) >= VARIANT_OPTION_CONTROL_SCAN_LIMIT:
                return options
            seen_control_ids.add(id(control))
            label = _option_control_label(control, label_map)
            availability, stock_quantity = variant_option_availability(
                node=control,
                label_node=label,
            )
            axis_key = _control_axis_key(control, label_map)
            if axis_key and axis_key not in _PUBLIC_AXIS_FIELDS:
                continue
            keys = _control_join_keys(control, label)
            if not keys:
                continue
            options.append(
                _DomOption(
                    availability=availability or AVAILABILITY_IN_STOCK,
                    stock_quantity=stock_quantity,
                    display=_control_display_label(control, label),
                    keys=keys,
                    axis_key=axis_key,
                )
            )
    return options


def _row_join_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field_name in _ROW_KEY_FIELDS:
        normalized = _normalized_key(row.get(field_name))
        if normalized:
            keys.add(normalized)
    option_values = row.get("option_values")
    if isinstance(option_values, dict):
        for value in option_values.values():
            normalized = _normalized_key(value)
            if normalized:
                keys.add(normalized)
    return keys


def _single_axis_key(variants: list[dict[str, Any]]) -> str | None:
    present_axes = _present_axis_keys(variants)
    return present_axes[0] if len(present_axes) == 1 else None


def _present_axis_keys(variants: list[dict[str, Any]]) -> list[str]:
    present_axes: list[str] = []
    for axis in _PUBLIC_AXIS_FIELDS:
        values = {
            _normalized_key(row.get(axis))
            for row in variants
            if text_or_none(row.get(axis))
        }
        values.discard("")
        if values:
            present_axes.append(axis)
    return present_axes


def _varying_axis_key(variants: list[dict[str, Any]]) -> str | None:
    varying_axes: list[str] = []
    for axis in _PUBLIC_AXIS_FIELDS:
        values = {
            _normalized_key(row.get(axis))
            for row in variants
            if text_or_none(row.get(axis))
        }
        values.discard("")
        if not values:
            continue
        if len(values) > 1:
            varying_axes.append(axis)
    return varying_axes[0] if len(varying_axes) == 1 else None


def _maybe_upgrade_axis_label(
    row: dict[str, Any],
    *,
    axis_key: str | None,
    display: str,
) -> None:
    """Upgrade a short option token to the richer rendered label.

    Only fires when the current value is a strict, shorter token of the rendered
    label (e.g. `5` -> `M 5 / W 6.5`), so we never overwrite a fuller value or a
    differently-formatted one.
    """
    if not axis_key or not display:
        return
    current = text_or_none(row.get(axis_key))
    if not current:
        return
    if current == display:
        return
    current_norm = _normalized_key(current)
    display_norm = _normalized_key(display)
    if not current_norm or current_norm == display_norm:
        return
    if len(display) <= len(current):
        return
    if current_norm not in display_norm:
        return
    if re.search(r"\b(?:choose|select)\b", display, flags=re.I):
        return
    row[axis_key] = display
    option_values = row.get("option_values")
    if (
        isinstance(option_values, dict)
        and _normalized_key(option_values.get(axis_key)) == current_norm
    ):
        option_values[axis_key] = display


def reconcile_variant_availability_from_dom(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup | None,
) -> None:
    if soup is None or not hasattr(soup, "select"):
        return
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
    if not variants:
        return
    dom_options = _collect_dom_options(soup)
    if not dom_options:
        return

    # Index DOM options by join key; out-of-stock evidence wins per key.
    index: dict[str, _DomOption] = {}
    for option in dom_options:
        for key in option.keys:
            existing = index.get(key)
            if existing is None or (
                existing.availability != AVAILABILITY_OUT_OF_STOCK
                and option.availability == AVAILABILITY_OUT_OF_STOCK
            ):
                index[key] = option

    label_axis_key = _varying_axis_key(variants) or _single_axis_key(variants)
    append_axis_key = _single_axis_key(variants)
    matched_options: set[int] = set()
    for row in variants:
        match: _DomOption | None = None
        for key in _row_join_keys(row):
            candidate = index.get(key)
            if candidate is None:
                continue
            if match is None or (
                candidate.availability == AVAILABILITY_OUT_OF_STOCK
                and match.availability != AVAILABILITY_OUT_OF_STOCK
            ):
                match = candidate
        if match is None:
            continue
        matched_options.add(id(match))
        _maybe_upgrade_axis_label(row, axis_key=label_axis_key, display=match.display)
        current = text_or_none(row.get("availability"))
        if match.availability == AVAILABILITY_OUT_OF_STOCK:
            if current != AVAILABILITY_OUT_OF_STOCK:
                row["availability"] = AVAILABILITY_OUT_OF_STOCK
            if match.stock_quantity is not None and row.get("stock_quantity") in (
                None,
                "",
                [],
                {},
            ):
                row["stock_quantity"] = match.stock_quantity
        elif match.availability == AVAILABILITY_IN_STOCK and not current:
            row["availability"] = AVAILABILITY_IN_STOCK

    _append_dom_only_out_of_stock_variants(
        record,
        variants=variants,
        axis_key=append_axis_key,
        dom_options=dom_options,
        matched_options=matched_options,
    )


def _append_dom_only_out_of_stock_variants(
    record: dict[str, Any],
    *,
    variants: list[dict[str, Any]],
    axis_key: str | None,
    dom_options: list[_DomOption],
    matched_options: set[int],
) -> None:
    """Append OOS options the structured tier omitted entirely.

    Only fires when the existing rows expose a single, consistent variant axis,
    so we never fabricate cross-axis combinations or pollute multi-axis records.
    """
    if axis_key is None:
        return
    existing_axis_keys = {
        _normalized_key(row.get(axis_key))
        for row in variants
        if text_or_none(row.get(axis_key))
    }
    appended = 0
    for option in dom_options:
        if id(option) in matched_options:
            continue
        if option.availability != AVAILABILITY_OUT_OF_STOCK:
            continue
        if option.axis_key and option.axis_key != axis_key:
            continue
        axis_value = option.display
        normalized_axis_value = _normalized_key(axis_value)
        if not normalized_axis_value or normalized_axis_value in existing_axis_keys:
            continue
        new_row: dict[str, Any] = {
            axis_key: axis_value,
            "option_values": {axis_key: axis_value},
            "availability": AVAILABILITY_OUT_OF_STOCK,
        }
        if option.stock_quantity is not None:
            new_row["stock_quantity"] = option.stock_quantity
        variants.append(new_row)
        existing_axis_keys.add(normalized_axis_value)
        appended += 1
    if appended:
        record["variants"] = variants
        record["variant_count"] = len(variants)
