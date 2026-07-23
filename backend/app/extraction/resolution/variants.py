"""Variant row assembly and publishability eligibility."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlsplit

from app.core.config.extraction_rules import (
    VARIANT_CROSS_PRODUCT_URL_MAX_TOKEN_OVERLAP_RATIO,
    VARIANT_DOM_URL_AXIS_PARAM_PATTERN,
    VARIANT_URL_AXIS_PARAMS,
    VARIANT_URL_OPTION_ENDPOINT_PATH_TOKENS,
)
from app.core.config.variant_policy import (
    DEFAULT_VARIANT_DIAGNOSTIC_REASON,
    DEFAULT_VARIANT_PLACEHOLDER_FLAG,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
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
    sku = row.get("sku")
    if row.get("variant_id") not in (None, "", [], {}, ()) or sku in (
        None,
        "",
        [],
        {},
        (),
    ):
        return
    row["variant_id"] = sku
    sku_lineage = lineage_row.get("sku")
    lineage_row["variant_id"] = {
        **(dict(sku_lineage) if isinstance(sku_lineage, Mapping) else {}),
        "rule_id": "variant_id_from_unique_sku",
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
    offer_by_variant: dict[str, OfferEntity] = {}
    for offer in entities.offers:
        if not offer.variant_entity_id:
            continue
        current = offer_by_variant.get(offer.variant_entity_id)
        if current is None or _offer_rank(offer) > _offer_rank(current):
            offer_by_variant[offer.variant_entity_id] = offer
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
    product_url = _resolved_product_url(decision_rows, evidence_by_id)
    candidates: list[tuple[VariantEntity, dict[str, object], dict[str, object]]] = []
    rejected: list[VariantDecision] = []
    for variant in entities.variants:
        values, lineage = _resolved_variant_row(
            variant,
            offer_by_variant.get(variant.entity_id),
            asset_by_variant.get(variant.entity_id),
            decisions,
            derived,
            evidence_by_id,
        )
        reason = _variant_rejection_reason(variant, values, product_url, evidence_by_id)
        if reason:
            rejected.append(
                _variant_decision(variant.entity_id, values, lineage, reason)
            )
        else:
            candidates.append((variant, values, lineage))
    eligible: list[VariantDecision] = []
    for variant, values, lineage in candidates:
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
    return tuple((*eligible, *rejected))


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
        "variant.gtin": "gtin",
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
        for field in ("variant_id", "sku", "gtin")
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
        decision = decisions.get((offer.entity_id, fact)) if offer else None
        decision = decision or decisions.get((variant.entity_id, fact))
        derived_fact = None
        if offer:
            derived_fact = derived.get((offer.entity_id, fact))
        derived_fact = derived_fact or derived.get((variant.entity_id, fact))
        if (
            not decision or not decision.accepted_evidence_ids
        ) and derived_fact is None:
            continue
        evidence = (
            evidence_by_id.get(decision.accepted_evidence_ids[0])
            if decision and decision.accepted_evidence_ids
            else None
        )
        if derived_fact is None and evidence is None:
            continue
        if derived_fact is not None:
            values[field] = derived_fact.value
            lineage[field] = _derived_lineage(derived_fact)
        elif evidence is not None and decision is not None:
            values[field] = evidence.value
            lineage[field] = _decision_lineage(decision)
    if values.get("price") not in (None, "", [], {}, ()) and values.get("currency") in (
        None,
        "",
        [],
        {},
        (),
    ):
        values.pop("price", None)
        values.pop("original_price", None)
        lineage.pop("price", None)
        lineage.pop("original_price", None)


def _variant_rejection_reason(
    variant,
    values,
    product_url: str,
    evidence_by_id: dict[str, Evidence],
) -> str | None:
    if not variant.identity_key:
        return "variant_missing_identity"
    if not _has_variant_option(values) and any(
        DEFAULT_VARIANT_PLACEHOLDER_FLAG in evidence_by_id[evidence_id].flags
        for evidence_id in variant.identity_evidence_ids
        if evidence_id in evidence_by_id
    ):
        return DEFAULT_VARIANT_DIAGNOSTIC_REASON
    explicit_identity = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("variant_id", "sku", "gtin")
    )
    commercial = any(
        values.get(field) not in (None, "", [], {}, ())
        for field in ("price", "availability", "stock_quantity")
    )
    if not _has_variant_option(values) and not (explicit_identity and commercial):
        return "variant_not_publishable"
    if not public_variant_row_is_sellable(values):
        return "variant_not_actionable"
    if _variant_url_conflicts(product_url, str(values.get("url") or ""), values):
        return "variant_url_conflicts_product"
    return None


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
    has_direct_commercial_fact = False
    for field in ("price", "availability", "stock_quantity"):
        field_lineage = lineage.get(field)
        if (
            isinstance(field_lineage, dict)
            and field_lineage.get("rule_id") != DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        ):
            has_direct_commercial_fact = True
            break
    return (
        has_structured_child_identity
        and has_direct_commercial_fact
        and any(
            values.get(field) not in (None, "", [], {}, ())
            for field in ("variant_id", "sku", "gtin")
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
        "gtin",
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
