"""Derived facts: money normalization, brand/currency/availability inference."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.config import field_mappings
from app.core.config.locale_format_rules import (
    CURRENCY_SYMBOL_TO_ISO,
    currency_hint_from_page_url,
)
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.core.records.title_normalization import strip_identity_trademark_symbols
from app.core.records.url_identity import detail_style_code_from_url
from app.core.shared.field_coerce_text import (
    infer_brand_from_marked_title_path,
    infer_brand_from_page_identity,
    infer_brand_from_product_url,
    infer_brand_from_title_marker,
)
from app.core.shared.ids import stable_id
from app.core.shared.text_coerce import slug_tokens
from app.extraction.contracts import Decision, DerivedFact, Evidence
from app.extraction.resolution.decisions import _invalidity_reason


def _derived(
    decisions: list[Decision],
    by_id: dict[str, Evidence],
    *,
    page_url: str = "",
) -> tuple[DerivedFact, ...]:
    out: list[DerivedFact] = []
    resolved_fact_keys = {
        (decision.entity_id, decision.fact_type)
        for decision in decisions
        if decision.status == "resolved"
    }
    resolved_values = {
        (decision.entity_id, decision.fact_type): by_id[
            decision.accepted_evidence_ids[0]
        ].value
        for decision in decisions
        if decision.status == "resolved"
        and decision.accepted_evidence_ids
        and decision.accepted_evidence_ids[0] in by_id
    }
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str] = {
        (decision.fact_type, decision.accepted_evidence_ids): stable_id(
            "selected", decision.decision_id
        )
        for decision in decisions
        if decision.status == "resolved"
        and len(decision.accepted_evidence_ids) == 1
        and decision.rule_id != DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
    }
    for decision in decisions:
        out.extend(
            _semantic_derived_facts(
                decision,
                by_id,
                page_url=page_url,
                direct_selected_ids=direct_selected_ids,
                resolved_fact_keys=resolved_fact_keys,
                resolved_values=resolved_values,
            )
        )
        money_fact = _money_precision_fact(decision, by_id, direct_selected_ids)
        if money_fact is not None:
            out.append(money_fact)
    return tuple(out)


def _money_precision_fact(
    decision: Decision,
    evidence_by_id: dict[str, Evidence],
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
) -> DerivedFact | None:
    if (
        decision.fact_type
        not in {
            field_mappings.OFFER_PRICE_FACT_TYPE,
            field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
        }
        or not decision.accepted_evidence_ids
    ):
        return None
    evidence = evidence_by_id[decision.accepted_evidence_ids[0]]
    try:
        value = f"{float(str(evidence.value).replace(',', '')):.2f}"
    except (TypeError, ValueError):
        return None
    rule_id = (
        decision.rule_id
        if decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        else "NORMALIZE_MONEY_PRECISION"
    )
    selected_id = direct_selected_ids.get(
        (decision.fact_type, decision.accepted_evidence_ids)
    )
    return DerivedFact(
        derived_fact_id=stable_id(
            "derived", rule_id, decision.entity_id, decision.fact_type, value
        ),
        entity_id=decision.entity_id,
        fact_type=decision.fact_type,
        value=value,
        input_evidence_ids=decision.accepted_evidence_ids,
        input_selected_fact_ids=(selected_id,) if selected_id else (),
        rule_id=rule_id,
    )


def _semantic_derived_facts(
    decision: Decision,
    by_id: dict[str, Evidence],
    *,
    page_url: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_fact_keys: set[tuple[str, str]],
    resolved_values: dict[tuple[str, str], object],
) -> tuple[DerivedFact, ...]:
    if decision.status != "resolved" or not decision.accepted_evidence_ids:
        return ()
    evidence = by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return ()
    if decision.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        return _title_brand_fact(
            decision,
            evidence,
            by_id,
            page_url=page_url,
            direct_selected_ids=direct_selected_ids,
            resolved_values=resolved_values,
        )
    if decision.fact_type == field_mappings.PRODUCT_URL_FACT_TYPE:
        return _url_sku_fact(
            decision,
            evidence,
            page_url=page_url,
            direct_selected_ids=direct_selected_ids,
            resolved_fact_keys=resolved_fact_keys,
        )
    if decision.fact_type == field_mappings.OFFER_PRICE_FACT_TYPE:
        return _price_currency_fact(
            decision,
            evidence,
            page_url=page_url,
            direct_selected_ids=direct_selected_ids,
            resolved_fact_keys=resolved_fact_keys,
        )
    if decision.fact_type == "offer.stock_quantity":
        return _stock_availability_fact(
            decision,
            evidence,
            direct_selected_ids=direct_selected_ids,
            resolved_fact_keys=resolved_fact_keys,
        )
    return ()


def _title_brand_fact(
    decision: Decision,
    evidence: Evidence,
    evidence_by_id: dict[str, Evidence],
    *,
    page_url: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_values: dict[tuple[str, str], object],
) -> tuple[DerivedFact, ...]:
    existing_brand = resolved_values.get(
        (decision.entity_id, field_mappings.PRODUCT_BRAND_FACT_TYPE)
    )
    if existing_brand:
        return ()
    brand_candidates = tuple(
        row
        for row in evidence_by_id.values()
        if row.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE
        and row.subject_id == evidence.subject_id
    )
    existing_brands = (
        (existing_brand,)
        if existing_brand
        else tuple(row.value for row in brand_candidates)
    )
    brand = _brand_from_title(
        evidence.value,
        marker_title=evidence.raw_value,  # pre-normalization boundary signal
        page_url=page_url,
        evidence_values=tuple(
            source_value
            for row in evidence_by_id.values()
            if row.fact_type != field_mappings.PRODUCT_URL_FACT_TYPE
            for source_value in (row.value, row.raw_value)
        ),
        existing_brands=existing_brands,
        allow_page_identity_replacement=(
            not existing_brand
            and any(_invalidity_reason(row) is not None for row in brand_candidates)
        ),
    )
    if not brand:
        return ()
    return (
        _derived_fact(
            decision,
            fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
            value=brand[0],
            rule_id=brand[1],
            direct_selected_ids=direct_selected_ids,
        ),
    )


def _url_sku_fact(
    decision: Decision,
    evidence: Evidence,
    *,
    page_url: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_fact_keys: set[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    if (
        decision.entity_id,
        field_mappings.PRODUCT_SKU_FACT_TYPE,
    ) in resolved_fact_keys:
        return ()
    sku = detail_style_code_from_url(str(evidence.value or page_url))
    if not sku:
        return ()
    return (
        _derived_fact(
            decision,
            fact_type=field_mappings.PRODUCT_SKU_FACT_TYPE,
            value=sku,
            rule_id="sku_from_url_style_code",
            direct_selected_ids=direct_selected_ids,
        ),
    )


def _price_currency_fact(
    decision: Decision,
    evidence: Evidence,
    *,
    page_url: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_fact_keys: set[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    if (
        decision.entity_id,
        field_mappings.OFFER_CURRENCY_FACT_TYPE,
    ) in resolved_fact_keys:
        return ()
    currency = _currency_for_price(evidence, page_url=page_url)
    if not currency:
        return ()
    return (
        _derived_fact(
            decision,
            fact_type=field_mappings.OFFER_CURRENCY_FACT_TYPE,
            value=currency[0],
            rule_id=currency[1],
            direct_selected_ids=direct_selected_ids,
        ),
    )


def _stock_availability_fact(
    decision: Decision,
    evidence: Evidence,
    *,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
    resolved_fact_keys: set[tuple[str, str]],
) -> tuple[DerivedFact, ...]:
    if (
        decision.entity_id,
        field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
    ) in resolved_fact_keys:
        return ()
    availability = _availability_from_stock_quantity(evidence)
    if not availability:
        return ()
    return (
        _derived_fact(
            decision,
            fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
            value=availability,
            rule_id="availability_from_stock_quantity",
            direct_selected_ids=direct_selected_ids,
        ),
    )


def _derived_fact(
    decision: Decision,
    *,
    fact_type: str,
    value: object,
    rule_id: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
) -> DerivedFact:
    selected_id = direct_selected_ids.get(
        (decision.fact_type, decision.accepted_evidence_ids)
    )
    return DerivedFact(
        derived_fact_id=stable_id(
            "derived", rule_id, decision.entity_id, fact_type, value
        ),
        entity_id=decision.entity_id,
        fact_type=fact_type,
        value=value,
        input_evidence_ids=decision.accepted_evidence_ids,
        input_selected_fact_ids=(selected_id,) if selected_id else (),
        rule_id=rule_id,
    )


def _currency_for_price(evidence: Evidence, *, page_url: str) -> tuple[str, str] | None:
    raw = evidence.raw_value if isinstance(evidence.raw_value, str) else ""
    symbols = {
        str(currency)
        for symbol, currency in CURRENCY_SYMBOL_TO_ISO.items()
        if str(symbol) in raw
    }
    if len(symbols) == 1:
        return symbols.pop(), "currency_from_price_symbol"
    if currency := currency_hint_from_page_url(page_url):
        return currency, "currency_from_page_url_hint"
    return None


def _availability_from_stock_quantity(evidence: Evidence) -> str | None:
    try:
        quantity = Decimal(str(evidence.value).strip())
    except (InvalidOperation, ValueError):
        return None
    return "in_stock" if quantity > 0 else "out_of_stock"


def _brand_from_title(
    title: object,
    *,
    page_url: str,
    marker_title: object = None,
    evidence_values: tuple[object, ...] = (),
    existing_brands: tuple[object, ...] = (),
    allow_page_identity_replacement: bool = False,
) -> tuple[str, str] | None:
    has_independent_product_signal = any(
        text and text.casefold() != str(title or "").strip().casefold()
        for value in evidence_values
        for text in (str(value or "").strip(),)
    )
    page_identity = _page_identity_brand(
        title,
        url=page_url,
        evidence_values=evidence_values,
        existing_brands=existing_brands,
        allow_replacement=allow_page_identity_replacement,
    )
    if existing_brands:
        return _replacement_brand(
            existing_brands[0],
            page_identity,
            allow_replacement=allow_page_identity_replacement,
        )
    if page_identity:
        return page_identity, "page_identity"
    return _new_title_brand(
        marked=marker_title if str(marker_title or "").strip() else title,
        page_url=page_url,
        has_independent_product_signal=has_independent_product_signal,
    )


def _page_identity_brand(
    title: object,
    *,
    url: str,
    evidence_values: tuple[object, ...],
    existing_brands: tuple[object, ...],
    allow_replacement: bool,
) -> str | None:
    page_identity = infer_brand_from_page_identity(
        url=url,
        title=title,
        evidence_values=evidence_values,
        existing_brands=existing_brands,
    )
    if page_identity is None and allow_replacement:
        return infer_brand_from_page_identity(
            url=url,
            title=title,
            evidence_values=evidence_values,
            existing_brands=(),
        )
    return page_identity


def _replacement_brand(
    existing_brand: object,
    page_identity: str | None,
    *,
    allow_replacement: bool,
) -> tuple[str, str] | None:
    if not page_identity:
        return None
    existing = str(existing_brand or "").strip().casefold()
    candidate = page_identity.strip()
    candidate_folded = candidate.casefold()
    if (
        candidate_folded.startswith(f"{existing} ")
        or existing.startswith(f"{candidate_folded} ")
        or allow_replacement
    ):
        return candidate, "page_identity"
    return None


def _new_title_brand(
    *,
    page_url: str,
    has_independent_product_signal: bool,
    marked: object,
) -> tuple[str, str] | None:
    # The marker locates where the brand name ends; it is not part of the name,
    # so the published brand drops it. The shared helper keeps the source form
    # because product-intelligence matching compares against raw snapshots.
    marker_brand = strip_identity_trademark_symbols(
        infer_brand_from_title_marker(marked) or ""
    )
    marked_path = infer_brand_from_marked_title_path(url=page_url, title=marked)
    if (
        marker_brand
        and len(slug_tokens(marker_brand)) == 1
        and has_independent_product_signal
    ):
        return marker_brand, "brand_from_title_marker"
    product_url = infer_brand_from_product_url(url=page_url, title=marked)
    for rule_id, value in (
        ("brand_from_marked_title_path", marked_path),
        ("brand_from_product_url", product_url),
        ("brand_from_title_marker", marker_brand),
    ):
        if value and has_independent_product_signal:
            return value, rule_id
    return None
