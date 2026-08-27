"""Variant row assembly and publishability eligibility."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlsplit

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_URL_AXIS_PARAMS,
    VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS,
)
from app.core.config.variant_policy import (
    AXIS_GROUP_VARIANT_DIAGNOSTIC_REASON,
    DEFAULT_VARIANT_DIAGNOSTIC_REASON,
    DEFAULT_VARIANT_PLACEHOLDER_FLAG,
    PUBLIC_VARIANT_AXIS_FIELDS,
    SIBLING_PRODUCT_VARIANT_DIAGNOSTIC_REASON,
    public_variant_row_is_sellable,
)
from app.core.records.url_identity import (
    detail_title_from_url,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce import sanitize_option_scalar
from app.core.shared.url_utils import public_asset_delivery_url
from app.extraction.contracts import (
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    VariantDecision,
)
from app.extraction.entities import (
    AssetEntity,
    EntitySet,
    OfferEntity,
    VariantEntity,
)
from app.extraction.resolution.assets import accepted_asset_evidence, asset_rank
from app.extraction.resolution.decisions import _resolve_scalar
from app.extraction.resolution.lineage import (
    _decision_lineage,
    _derived_lineage,
    _put_decision_value,
    _resolved_product_url,
)
from app.extraction.resolution.offers import _offer_rank


def inherit_variant_id_from_sku(
    row: dict[str, object], lineage_row: dict[str, object]
) -> None:
    source_field = "barcode" if row.get("barcode") else "sku"
    identity = row.get(source_field)
    if row.get("variant_id") not in (None, "", [], {}, ()) or identity in (
        None,
        "",
        [],
        {},
        (),
    ):
        return
    row["variant_id"] = identity
    identity_lineage = lineage_row.get(source_field)
    lineage_row["variant_id"] = {
        **(dict(identity_lineage) if isinstance(identity_lineage, Mapping) else {}),
        "rule_id": (
            "variant_id_from_unique_gtin"
            if source_field == "barcode"
            else "variant_id_from_unique_sku"
        ),
    }


def _resolve_variants(
    entities: EntitySet,
    decision_rows: list[Decision],
    derived_rows: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[VariantDecision, ...]:
    decisions = {
        (row.entity_id, row.fact_type): row
        for row in decision_rows
        if row.status == "resolved"
    }
    derived = {(row.entity_id, row.fact_type): row for row in derived_rows}
    offer_by_variant = _preferred_offer_by_variant(entities)
    asset_by_variant = _preferred_asset_by_variant(entities, evidence_by_id)
    product_url = _resolved_product_url(decision_rows, evidence_by_id)
    candidates, rejected = _variant_candidates(
        entities,
        offer_by_variant,
        asset_by_variant,
        decisions,
        derived,
        evidence_by_id,
        product_url=product_url,
    )
    eligible, optionless_rejected = _eligible_variant_decisions(
        candidates, evidence_by_id
    )
    return tuple((*eligible, *rejected, *optionless_rejected))


def _preferred_offer_by_variant(entities: EntitySet) -> dict[str, OfferEntity]:
    offer_by_variant: dict[str, OfferEntity] = {}
    for offer in entities.offers:
        if not offer.variant_entity_id:
            continue
        current = offer_by_variant.get(offer.variant_entity_id)
        if current is None or _offer_rank(offer) > _offer_rank(current):
            offer_by_variant[offer.variant_entity_id] = offer
    return offer_by_variant


def _preferred_asset_by_variant(
    entities: EntitySet, evidence_by_id: dict[str, Evidence]
) -> dict[str, AssetEntity]:
    asset_by_variant: dict[str, AssetEntity] = {}
    for asset in entities.assets:
        if not asset.variant_entity_id:
            continue
        accepted = accepted_asset_evidence(asset, evidence_by_id)
        current_asset = asset_by_variant.get(asset.variant_entity_id)
        current_accepted = (
            accepted_asset_evidence(current_asset, evidence_by_id)
            if current_asset
            else None
        )
        if current_asset is None or asset_rank(asset, accepted) < asset_rank(
            current_asset, current_accepted
        ):
            asset_by_variant[asset.variant_entity_id] = asset
    return asset_by_variant


def _variant_candidates(
    entities: EntitySet,
    offer_by_variant: dict[str, OfferEntity],
    asset_by_variant: dict[str, AssetEntity],
    decisions: dict[tuple[str, str], Decision],
    derived: dict[tuple[str, str], DerivedFact],
    evidence_by_id: dict[str, Evidence],
    *,
    product_url: str,
) -> tuple[
    list[tuple[VariantEntity, dict[str, object], dict[str, object]]],
    list[VariantDecision],
]:
    candidates: list[tuple[VariantEntity, dict[str, object], dict[str, object]]] = []
    rejected: list[VariantDecision] = []
    resolved = [
        (
            variant,
            *_resolved_variant_row(
                variant,
                offer_by_variant.get(variant.entity_id),
                asset_by_variant.get(variant.entity_id),
                decisions,
                derived,
                evidence_by_id,
            ),
        )
        for variant in entities.variants
    ]
    values_by_product = {
        product_id: [
            values
            for variant, values, _lineage in resolved
            if variant.product_entity_id == product_id
        ]
        for product_id in {variant.product_entity_id for variant in entities.variants}
    }
    for variant, values, lineage in resolved:
        reason = _variant_rejection_reason(
            variant,
            values,
            product_url,
            evidence_by_id,
            product_title=_resolved_product_title(
                variant.product_entity_id, decisions, evidence_by_id
            ),
        )
        if reason is None and _variant_sku_conflicts_product_family(
            values,
            product_sku=_resolved_product_value(
                variant.product_entity_id,
                field_mappings.PRODUCT_SKU_FACT_TYPE,
                decisions,
                evidence_by_id,
            ),
            sibling_values=values_by_product[variant.product_entity_id],
        ):
            reason = SIBLING_PRODUCT_VARIANT_DIAGNOSTIC_REASON
        if reason:
            rejected.append(
                _variant_decision(variant.entity_id, values, lineage, reason)
            )
        else:
            candidates.append((variant, values, lineage))
    return candidates, rejected


def _resolved_product_title(
    product_id: str,
    decisions: dict[tuple[str, str], Decision],
    evidence_by_id: dict[str, Evidence],
) -> str:
    return _resolved_product_value(
        product_id,
        field_mappings.PRODUCT_TITLE_FACT_TYPE,
        decisions,
        evidence_by_id,
    )


def _resolved_product_value(
    product_id: str,
    fact_type: str,
    decisions: dict[tuple[str, str], Decision],
    evidence_by_id: dict[str, Evidence],
) -> str:
    decision = decisions.get((product_id, fact_type))
    if not decision or not decision.accepted_evidence_ids:
        return ""
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    return str(evidence.value).strip() if evidence else ""


def _variant_sku_conflicts_product_family(
    values: Mapping[str, object],
    *,
    product_sku: str,
    sibling_values: list[dict[str, object]],
) -> bool:
    """Reject sibling style rows when the product SKU identifies one family."""
    parent_key = _identifier_family_key(product_sku)
    variant_key = _identifier_family_key(values.get("sku"))
    if len(parent_key) < 5 or not variant_key:
        return False
    sibling_keys = {_identifier_family_key(row.get("sku")) for row in sibling_values}
    if parent_key in sibling_keys:
        return False
    return parent_key not in variant_key and any(
        parent_key in sibling_key for sibling_key in sibling_keys
    )


def _identifier_family_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _eligible_variant_decisions(
    candidates: list[tuple[VariantEntity, dict[str, object], dict[str, object]]],
    evidence_by_id: dict[str, Evidence],
) -> tuple[list[VariantDecision], list[VariantDecision]]:
    eligible: list[VariantDecision] = []
    rejected: list[VariantDecision] = []
    candidate_values = [values for _variant, values, _lineage in candidates]
    for variant, values, lineage in candidates:
        if _is_axis_group_variant(values, candidate_values):
            rejected.append(
                _variant_decision(
                    variant.entity_id,
                    values,
                    lineage,
                    AXIS_GROUP_VARIANT_DIAGNOSTIC_REASON,
                )
            )
            continue
        if (
            len(candidates) > 1
            and not _has_variant_option(values)
            and not _explicit_partial_child_is_publishable(
                variant, values, lineage, evidence_by_id
            )
        ):
            rejected.append(
                _variant_decision(
                    variant.entity_id,
                    values,
                    lineage,
                    "optionless_variant_among_options",
                )
            )
            continue
        eligible.append(
            VariantDecision(
                variant_entity_id=variant.entity_id,
                status="eligible",
                reason_code="variant_eligible",
                values=values,
                lineage=lineage,
            )
        )
    return eligible, rejected


def _is_axis_group_variant(
    values: dict[str, object],
    candidates: list[dict[str, object]],
) -> bool:
    """Reject an option-group shell when commercial leaf variants are explicit."""
    options = _variant_option_values(values)
    if not options or _has_variant_commercial_value(values):
        return False
    return any(
        len(child_options := _variant_option_values(child_values)) > len(options)
        and options.items() <= child_options.items()
        and _has_variant_commercial_value(child_values)
        for child_values in candidates
        if child_values is not values
    )


def _variant_option_values(values: dict[str, object]) -> dict[str, object]:
    return {
        field: values[field]
        for field in PUBLIC_VARIANT_AXIS_FIELDS
        if values.get(field) not in (None, "", [], {}, ())
    }


def _has_variant_commercial_value(values: dict[str, object]) -> bool:
    return any(
        values.get(field) not in (None, "", [], {}, ())
        for field in (
            "price",
            "original_price",
            "availability",
            "stock_quantity",
        )
    )


def _resolved_variant_row(
    variant: VariantEntity,
    offer: OfferEntity | None,
    asset: AssetEntity | None,
    decisions: dict[tuple[str, str], Decision],
    derived: dict[tuple[str, str], DerivedFact],
    evidence_by_id: dict[str, Evidence],
) -> tuple[dict[str, object], dict[str, object]]:
    values: dict[str, object] = {}
    lineage: dict[str, object] = {}
    for fact, field in {
        "variant.id": "variant_id",
        "variant.sku": "sku",
        "variant.gtin": "barcode",
        "variant.url": "url",
    }.items():
        _put_decision_value(
            values,
            lineage,
            field,
            decisions.get((variant.entity_id, fact)),
            evidence_by_id,
        )
    inherit_variant_id_from_sku(values, lineage)
    _put_variant_options(values, lineage, variant, decisions, evidence_by_id)
    _put_variant_offer(
        values, lineage, variant, offer, decisions, derived, evidence_by_id
    )
    asset_decision = (
        decisions.get((asset.entity_id, "asset.image_url")) if asset else None
    )
    if asset and asset_decision and asset_decision.accepted_evidence_ids:
        evidence = evidence_by_id.get(asset_decision.accepted_evidence_ids[0])
        delivery_url = public_asset_delivery_url(evidence.value) if evidence else None
        if delivery_url:
            values["image_url"] = delivery_url
            lineage["image_url"] = _decision_lineage(asset_decision)
    return values, lineage


def _put_variant_options(values, lineage, variant, decisions, evidence_by_id) -> None:
    identity_values = {
        str(values.get(field) or "").strip().casefold()
        for field in ("variant_id", "sku", "barcode")
        if str(values.get(field) or "").strip()
    }
    for (entity_id, fact_type), decision in decisions.items():
        if entity_id != variant.entity_id or not fact_type.startswith(
            "variant.option."
        ):
            continue
        field = fact_type.rsplit(".", 1)[-1]
        evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
        value = sanitize_option_scalar(field, evidence.value) if evidence else None
        if value is None or value.casefold() in identity_values:
            continue
        values[field] = value
        lineage[field] = _decision_lineage(decision)


def _put_variant_offer(
    values, lineage, variant, offer, decisions, derived, evidence_by_id
) -> None:
    for fact, field in {
        "offer.price": "price",
        "offer.currency": "currency",
        "offer.original_price": "original_price",
        "offer.availability": "availability",
        "offer.stock_quantity": "stock_quantity",
    }.items():
        _put_variant_offer_value(
            values,
            lineage,
            variant,
            offer,
            decisions,
            derived,
            evidence_by_id,
            fact=fact,
            field=field,
        )
    _drop_unpaired_variant_price(values, lineage)


def _put_variant_offer_value(
    values: dict[str, object],
    lineage: dict[str, object],
    variant: VariantEntity,
    offer: OfferEntity | None,
    decisions: dict[tuple[str, str], Decision],
    derived: dict[tuple[str, str], DerivedFact],
    evidence_by_id: dict[str, Evidence],
    *,
    fact: str,
    field: str,
) -> None:
    decision = decisions.get((offer.entity_id, fact)) if offer else None
    decision = decision or decisions.get((variant.entity_id, fact))
    derived_fact = derived.get((offer.entity_id, fact)) if offer else None
    derived_fact = derived_fact or derived.get((variant.entity_id, fact))
    if (not decision or not decision.accepted_evidence_ids) and derived_fact is None:
        return
    evidence = (
        evidence_by_id.get(decision.accepted_evidence_ids[0])
        if decision and decision.accepted_evidence_ids
        else None
    )
    if derived_fact is not None:
        values[field] = derived_fact.value
        lineage[field] = _derived_lineage(derived_fact)
    elif evidence is not None and decision is not None:
        values[field] = evidence.value
        lineage[field] = _decision_lineage(decision)


def _drop_unpaired_variant_price(
    values: dict[str, object], lineage: dict[str, object]
) -> None:
    if values.get("price") in (None, "", [], {}, ()) or values.get("currency") not in (
        None,
        "",
        [],
        {},
        (),
    ):
        return
    values.pop("price", None)
    values.pop("original_price", None)
    lineage.pop("price", None)
    lineage.pop("original_price", None)


def _variant_rejection_reason(
    variant,
    values,
    product_url: str,
    evidence_by_id: dict[str, Evidence],
    *,
    product_title: str,
) -> str | None:
    if not variant.identity_key:
        return "variant_missing_identity"
    if not _has_variant_option(values) and any(
        DEFAULT_VARIANT_PLACEHOLDER_FLAG in evidence_by_id[evidence_id].flags
        for evidence_id in variant.identity_evidence_ids
        if evidence_id in evidence_by_id
    ):
        return DEFAULT_VARIANT_DIAGNOSTIC_REASON
    if not _has_variant_option(values) and not _optionless_variant_is_publishable(
        values
    ):
        return "variant_not_publishable"
    if not public_variant_row_is_sellable(values):
        return "variant_not_actionable"
    if _variant_option_repeats_product_title(values, product_title):
        return DEFAULT_VARIANT_DIAGNOSTIC_REASON
    if _variant_url_conflicts(
        product_url, str(values.get("url") or ""), values
    ) and not _has_explicit_product_variant_relation(variant, evidence_by_id):
        return "variant_url_conflicts_product"
    return None


def _optionless_variant_is_publishable(values: Mapping[str, object]) -> bool:
    has_identity = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("variant_id", "sku", "barcode")
    )
    has_commercial = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("price", "availability", "stock_quantity")
    )
    return has_identity and has_commercial


def _variant_option_repeats_product_title(values, product_title: str) -> bool:
    options = [
        str(values.get(field) or "").strip()
        for field in PUBLIC_VARIANT_AXIS_FIELDS
        if str(values.get(field) or "").strip()
    ]
    return bool(
        len(options) == 1
        and product_title
        and semantic_identity_tokens(options[0])
        == semantic_identity_tokens(product_title)
    )


def _has_direct_variant_commercial_fact(lineage: Mapping[str, object]) -> bool:
    return any(
        isinstance(field_lineage := lineage.get(field), dict)
        and bool(
            field_lineage.get("decision_id") or field_lineage.get("selected_fact_ids")
        )
        for field in ("price", "availability", "stock_quantity")
    )


def _has_explicit_product_variant_relation(
    variant: VariantEntity, evidence_by_id: dict[str, Evidence]
) -> bool:
    return any(
        (row := evidence_by_id.get(evidence_id)) is not None
        and row.collector_id == "jsonld"
        and row.relation_type == "product_variant"
        for evidence_id in variant.identity_evidence_ids
    )


def _explicit_partial_child_is_publishable(
    variant: VariantEntity,
    values: dict[str, object],
    lineage: dict[str, object],
    evidence_by_id: dict[str, Evidence],
) -> bool:
    has_structured_child_identity = any(
        (row := evidence_by_id.get(evidence_id)) is not None
        and row.collector_id == "jsonld"
        and row.relation_type == "product_variant"
        and row.fact_type in {"variant.id", "variant.sku", "variant.gtin"}
        for evidence_id in variant.identity_evidence_ids
    )
    return (
        has_structured_child_identity
        and _has_direct_variant_commercial_fact(lineage)
        and any(
            values.get(field) not in (None, "", [], {}, ())
            for field in ("variant_id", "sku", "barcode")
        )
    )


def _variant_url_conflicts(product_url: str, variant_url: str, values) -> bool:
    if not product_url or not variant_url or product_url == variant_url:
        return False
    if _variant_url_is_option_endpoint(product_url, variant_url, values):
        return False
    product_tokens = set(semantic_identity_tokens(detail_title_from_url(product_url)))
    variant_tokens = set(semantic_identity_tokens(detail_title_from_url(variant_url)))
    if len(product_tokens) < 2 or len(variant_tokens) < 2:
        return False
    overlap = len(product_tokens & variant_tokens) / min(
        len(product_tokens), len(variant_tokens)
    )
    if overlap <= VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO:
        return True
    if urlsplit(product_url).path.rstrip("/") == urlsplit(variant_url).path.rstrip("/"):
        return False
    option_tokens = {
        token
        for field in ("color", "size", "style", "material", "gender")
        for token in semantic_identity_tokens(str(values.get(field) or ""))
    }
    return bool((variant_tokens - product_tokens) - option_tokens)


def _variant_url_is_option_endpoint(
    product_url: str, variant_url: str, values: Mapping[str, object]
) -> bool:
    product_host = urlsplit(product_url).netloc.casefold()
    variant_parts = urlsplit(variant_url)
    if (
        product_host
        and variant_parts.netloc
        and product_host != variant_parts.netloc.casefold()
    ):
        return False
    path_tokens = set(semantic_identity_tokens(detail_title_from_url(variant_url)))
    if not (path_tokens & VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS):
        return False
    matched_axis = False
    for key, value in parse_qsl(variant_parts.query, keep_blank_values=False):
        axis_match = re.match(VARIANT_DOM_URL_AXIS_PARAM_PATTERN, key, flags=re.I)
        if not axis_match:
            continue
        axis = VARIANT_URL_AXIS_PARAMS.get(axis_match.group("axis").casefold())
        if not axis or values.get(axis) in (None, "", [], {}, ()):
            continue
        query_tokens = set(semantic_identity_tokens(value))
        axis_value_tokens = set(semantic_identity_tokens(str(values.get(axis) or "")))
        if query_tokens and query_tokens <= axis_value_tokens:
            matched_axis = True
    return matched_axis


def _has_variant_option(values) -> bool:
    transport = {
        "variant_id",
        "sku",
        "barcode",
        "url",
        "image_url",
        "price",
        "currency",
        "availability",
        "stock_quantity",
    }
    return any(
        key not in transport and value not in (None, "", [], {}, ())
        for key, value in values.items()
    )


def _variant_decision(entity_id, values, lineage, reason) -> VariantDecision:
    return VariantDecision(
        variant_entity_id=entity_id,
        status="rejected",
        reason_code=reason,
        values=values,
        lineage=lineage,
    )


def _resolve_variant(
    variant: VariantEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> tuple[Decision, ...]:
    return tuple(
        _resolve_scalar(variant.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(variant.attribute_evidence.items())
    )
