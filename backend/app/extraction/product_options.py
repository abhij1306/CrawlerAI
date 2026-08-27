from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Self, TypeVar

from app.core.config.extraction_rules import (
    VARIANT_DOM_SELECTION_SIGNAL_METADATA_KEY,
    VARIANT_DOM_SELECTION_SOURCE_METADATA_KEY,
    VARIANT_DOM_SELECTION_STANDARD_SOURCE,
    VARIANT_DOM_SELECTION_VALUE_METADATA_KEY,
    is_rejected_option_value,
)
from app.core.records.url_identity import selected_variant_axes
from app.extraction.contracts import (
    CaptureBundle,
    Evidence,
    OptionAxis,
    OptionValue,
    ProductOptionCatalog,
)


class VariantSelectionCandidate(Protocol):
    entity_id: str
    product_entity_id: str
    identity_keys: tuple[str, ...]
    option_values: dict[str, str]
    attribute_evidence: dict[str, tuple[str, ...]]
    selected: bool

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self: ...


VariantT = TypeVar("VariantT", bound=VariantSelectionCandidate)


@dataclass(frozen=True)
class _SelectionSignal:
    product_id: str
    axis: str
    value: str
    selected: bool
    source: str
    rows: tuple[Evidence, ...]


def build_option_catalogs(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
) -> tuple[ProductOptionCatalog, ...]:
    by_product: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in evidence:
        if not row.fact_type.startswith("option."):
            continue
        product_id = product_by_subject.get(row.subject_id)
        value = str(row.value)
        if not product_id or is_rejected_option_value(value):
            continue
        axis = row.fact_type.removeprefix("option.")
        by_product[product_id][axis][value].append(row.evidence_id)
    return tuple(
        ProductOptionCatalog(
            product_entity_id=product_id,
            axes=tuple(
                OptionAxis(
                    axis=axis,
                    values=tuple(
                        OptionValue(value=value, evidence_ids=tuple(sorted(ids)))
                        for value, ids in sorted(values.items())
                    ),
                )
                for axis, values in sorted(axes.items())
            ),
            evidence_ids=tuple(
                sorted(
                    evidence_id
                    for values in axes.values()
                    for ids in values.values()
                    for evidence_id in ids
                )
            ),
        )
        for product_id, axes in sorted(by_product.items())
    )


def apply_dom_variant_selection(
    bundle: CaptureBundle,
    evidence: tuple[Evidence, ...],
    variants: tuple[VariantT, ...],
    product_by_subject: dict[str, str],
) -> tuple[VariantT, ...]:
    selected = _unambiguous_selected_signals(evidence, variants, product_by_subject)
    if not selected:
        return variants
    url_axes = selected_variant_axes(bundle.requested_url)
    updates: dict[str, dict[str, object]] = {}
    for product_id, dom_signals in selected.items():
        updates.update(
            _product_selection_updates(product_id, dom_signals, url_axes, variants)
        )
    return tuple(
        variant.model_copy(update=updates.get(variant.entity_id))
        if variant.entity_id in updates
        else variant
        for variant in variants
    )


def is_dom_selection_signal(row: Evidence) -> bool:
    return row.metadata.get(VARIANT_DOM_SELECTION_SIGNAL_METADATA_KEY) is True


def _unambiguous_selected_signals(
    evidence: tuple[Evidence, ...],
    variants: tuple[VariantSelectionCandidate, ...],
    product_by_subject: dict[str, str],
) -> dict[str, dict[str, _SelectionSignal]]:
    grouped: dict[str, list[Evidence]] = defaultdict(list)
    for row in evidence:
        if is_dom_selection_signal(row):
            grouped[row.subject_id].append(row)
    candidates: dict[tuple[str, str], list[_SelectionSignal]] = defaultdict(list)
    for rows in grouped.values():
        signal = _selection_signal(tuple(rows), variants, product_by_subject)
        if signal is not None:
            candidates[(signal.product_id, signal.axis)].append(signal)
    selected: dict[str, dict[str, _SelectionSignal]] = defaultdict(dict)
    for (product_id, axis), signals in candidates.items():
        standard = [
            signal
            for signal in signals
            if signal.source == VARIANT_DOM_SELECTION_STANDARD_SOURCE
        ]
        preferred = standard or signals
        marked = _one_marked_value(preferred)
        if marked is not None:
            selected[product_id][axis] = marked
    return dict(selected)


def _selection_signal(
    rows: tuple[Evidence, ...],
    variants: tuple[VariantSelectionCandidate, ...],
    product_by_subject: dict[str, str],
) -> _SelectionSignal | None:
    state = next((row for row in rows if row.fact_type == "variant.selected"), None)
    product_id = _single_product_owner(rows, product_by_subject)
    if state is None or product_id is None:
        return None
    option = next(
        (row for row in rows if row.fact_type.startswith("variant.option.")), None
    )
    value = str(
        option.value
        if option is not None
        else state.metadata.get(VARIANT_DOM_SELECTION_VALUE_METADATA_KEY) or ""
    )
    axis = option.fact_type.removeprefix("variant.option.") if option else ""
    axis = _resolved_axis(product_id, axis, value, variants)
    if not axis or not value:
        return None
    return _SelectionSignal(
        product_id=product_id,
        axis=axis,
        value=value,
        selected=state.value is True,
        source=str(state.metadata.get(VARIANT_DOM_SELECTION_SOURCE_METADATA_KEY) or ""),
        rows=rows,
    )


def _product_selection_updates(
    product_id: str,
    dom_signals: dict[str, _SelectionSignal],
    url_axes: dict[str, str],
    variants: tuple[VariantSelectionCandidate, ...],
) -> dict[str, dict[str, object]]:
    active_signals = {
        axis: signal for axis, signal in dom_signals.items() if axis not in url_axes
    }
    if not active_signals:
        return {}
    axes = {axis: signal.value for axis, signal in active_signals.items()}
    axes.update(url_axes)
    candidates = tuple(
        variant for variant in variants if variant.product_entity_id == product_id
    )
    match_ids = {
        variant.entity_id for variant in candidates if _variant_matches(variant, axes)
    }
    if not match_ids:
        return {}
    signal_rows = tuple(
        row for signal in active_signals.values() for row in signal.rows
    )
    updates: dict[str, dict[str, object]] = {}
    for variant in candidates:
        update: dict[str, object] = {"selected": variant.entity_id in match_ids}
        if variant.entity_id in match_ids:
            update["attribute_evidence"] = _merged_attribute_evidence(
                variant.attribute_evidence, signal_rows
            )
        updates[variant.entity_id] = update
    return updates


def _one_marked_value(
    signals: list[_SelectionSignal],
) -> _SelectionSignal | None:
    by_value: dict[str, list[_SelectionSignal]] = defaultdict(list)
    for signal in signals:
        by_value[_normalized(signal.value)].append(signal)
    if any(
        len({signal.selected for signal in rows}) != 1 for rows in by_value.values()
    ):
        return None
    marked = [rows[0] for rows in by_value.values() if rows[0].selected]
    return marked[0] if len(marked) == 1 else None


def _single_product_owner(
    rows: tuple[Evidence, ...], product_by_subject: dict[str, str]
) -> str | None:
    owners = {
        product_by_subject[parent_id]
        for row in rows
        if (parent_id := row.parent_subject_id) in product_by_subject
    }
    return next(iter(owners)) if len(owners) == 1 else None


def _resolved_axis(
    product_id: str,
    requested_axis: str,
    value: str,
    variants: tuple[VariantSelectionCandidate, ...],
) -> str:
    candidates = tuple(
        variant for variant in variants if variant.product_entity_id == product_id
    )
    available_axes = {axis for variant in candidates for axis in variant.option_values}
    if requested_axis in available_axes:
        return requested_axis
    normalized = _normalized(value)
    matching_axes = {
        axis
        for variant in candidates
        for axis, option_value in variant.option_values.items()
        if _normalized(option_value) == normalized
    }
    return next(iter(matching_axes)) if len(matching_axes) == 1 else ""


def _variant_matches(variant: VariantSelectionCandidate, axes: dict[str, str]) -> bool:
    for axis, expected in axes.items():
        normalized = _normalized(expected)
        if axis == "sku":
            actual = {
                _normalized(key.split(":", 1)[1])
                for key in variant.identity_keys
                if key.startswith("sku:")
            }
            if normalized not in actual:
                return False
            continue
        if _normalized(variant.option_values.get(axis, "")) != normalized:
            return False
    return True


def _merged_attribute_evidence(
    existing: dict[str, tuple[str, ...]], rows: tuple[Evidence, ...]
) -> dict[str, tuple[str, ...]]:
    merged = dict(existing)
    for row in rows:
        merged[row.fact_type] = tuple(
            sorted({*merged.get(row.fact_type, ()), row.evidence_id})
        )
    return merged


def _normalized(value: object) -> str:
    return " ".join(str(value or "").casefold().split())
