"""Derived facts: money normalization, brand/currency/availability inference."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.config import field_mappings
from app.core.config.locale_format_rules import (
    CURRENCY_SYMBOL_TO_ISO,
    currency_hint_from_page_url,
)
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
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
        if (
            decision.fact_type
            not in {
                field_mappings.OFFER_PRICE_FACT_TYPE,
                field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
            }
            or not decision.accepted_evidence_ids
        ):
            continue
        ev = by_id[decision.accepted_evidence_ids[0]]
        try:
            value = f"{float(str(ev.value).replace(',', '')):.2f}"
        except (TypeError, ValueError):
            continue
        rule_id = (
            decision.rule_id
            if decision.rule_id == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
            else "NORMALIZE_MONEY_PRECISION"
        )
        out.append(
            DerivedFact(
                derived_fact_id=stable_id(
                    "derived", rule_id, decision.entity_id, decision.fact_type, value
                ),
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                value=value,
                input_evidence_ids=decision.accepted_evidence_ids,
                input_selected_fact_ids=tuple(
                    filter(
                        None,
                        (
                            direct_selected_ids.get(
                                (decision.fact_type, decision.accepted_evidence_ids)
                            ),
                        ),
                    )
                ),
                rule_id=rule_id,
            )
        )
    return tuple(out)


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
        existing_brand = resolved_values.get(
            (decision.entity_id, field_mappings.PRODUCT_BRAND_FACT_TYPE)
        )
        brand_candidates = tuple(
            row
            for row in by_id.values()
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
            page_url=page_url,
            evidence_values=tuple(
                row.value
                for row in by_id.values()
                if row.fact_type != field_mappings.PRODUCT_URL_FACT_TYPE
            ),
            existing_brands=existing_brands,
            allow_page_identity_replacement=(
                not existing_brand
                and any(_invalidity_reason(row) is not None for row in brand_candidates)
            ),
        )
        if brand:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.PRODUCT_BRAND_FACT_TYPE,
                    value=brand[0],
                    rule_id=brand[1],
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == field_mappings.PRODUCT_URL_FACT_TYPE
        and (decision.entity_id, field_mappings.PRODUCT_SKU_FACT_TYPE)
        not in resolved_fact_keys
    ):
        sku = detail_style_code_from_url(str(evidence.value or page_url))
        if sku:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.PRODUCT_SKU_FACT_TYPE,
                    value=sku,
                    rule_id="sku_from_url_style_code",
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == field_mappings.OFFER_PRICE_FACT_TYPE
        and (decision.entity_id, field_mappings.OFFER_CURRENCY_FACT_TYPE)
        not in resolved_fact_keys
    ):
        currency = _currency_for_price(evidence, page_url=page_url)
        if currency:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.OFFER_CURRENCY_FACT_TYPE,
                    value=currency[0],
                    rule_id=currency[1],
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    if (
        decision.fact_type == "offer.stock_quantity"
        and (decision.entity_id, field_mappings.OFFER_AVAILABILITY_FACT_TYPE)
        not in resolved_fact_keys
    ):
        availability = _availability_from_stock_quantity(evidence)
        if availability:
            return (
                _derived_fact(
                    decision,
                    fact_type=field_mappings.OFFER_AVAILABILITY_FACT_TYPE,
                    value=availability,
                    rule_id="availability_from_stock_quantity",
                    direct_selected_ids=direct_selected_ids,
                ),
            )
    return ()


def _derived_fact(
    decision: Decision,
    *,
    fact_type: str,
    value: object,
    rule_id: str,
    direct_selected_ids: dict[tuple[str, tuple[str, ...]], str],
) -> DerivedFact:
    return DerivedFact(
        derived_fact_id=stable_id(
            "derived",
            rule_id,
            decision.entity_id,
            fact_type,
            value,
        ),
        entity_id=decision.entity_id,
        fact_type=fact_type,
        value=value,
        input_evidence_ids=decision.accepted_evidence_ids,
        input_selected_fact_ids=tuple(
            filter(
                None,
                (
                    direct_selected_ids.get(
                        (decision.fact_type, decision.accepted_evidence_ids)
                    ),
                ),
            )
        ),
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
    evidence_values: tuple[object, ...] = (),
    existing_brands: tuple[object, ...] = (),
    allow_page_identity_replacement: bool = False,
) -> tuple[str, str] | None:
    has_independent_product_signal = any(
        text and text.casefold() != str(title or "").strip().casefold()
        for value in evidence_values
        for text in (str(value or "").strip(),)
    )
    page_identity = infer_brand_from_page_identity(
        url=page_url,
        title=title,
        evidence_values=evidence_values,
        existing_brands=existing_brands,
    )
    if page_identity is None and allow_page_identity_replacement:
        page_identity = infer_brand_from_page_identity(
            url=page_url,
            title=title,
            evidence_values=evidence_values,
            existing_brands=(),
        )
    if existing_brands and page_identity:
        existing = str(existing_brands[0] or "").strip()
        page_text = str(page_identity or "").strip()
        existing_folded = existing.casefold()
        page_folded = page_text.casefold()
        expands_existing = page_folded.startswith(f"{existing_folded} ")
        trims_product_suffix = existing_folded.startswith(f"{page_folded} ")
        if expands_existing or trims_product_suffix or allow_page_identity_replacement:
            return page_identity, "page_identity"
        return None
    if existing_brands:
        return None
    marker_brand = infer_brand_from_title_marker(title)
    if (
        marker_brand
        and len(slug_tokens(marker_brand)) == 1
        and has_independent_product_signal
    ):
        return marker_brand, "brand_from_title_marker"
    for rule_id, value in (
        (
            "brand_from_marked_title_path",
            infer_brand_from_marked_title_path(url=page_url, title=title),
        ),
        (
            "brand_from_product_url",
            infer_brand_from_product_url(url=page_url, title=title),
        ),
        ("brand_from_title_marker", marker_brand),
    ):
        if value and has_independent_product_signal:
            return value, rule_id
    return None
