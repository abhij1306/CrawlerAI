from urllib.parse import parse_qsl, urlsplit

from app.core.config.extraction_rules import IMAGE_DIMENSION_QUERY_KEYS
from app.core.config.extraction_rules._images import PRODUCT_ASSET_MAX_COUNT
from app.core.shared.url_utils import (
    asset_url_identity,
    is_utility_image_url,
    public_asset_delivery_url,
    structured_extensionless_image_url,
)
from app.extraction.contracts import AssetDecision, Evidence, VariantDecision
from app.extraction.entities import AssetEntity, VariantEntity
from app.extraction.resolution.ranking import rank


def normalize_asset_url(value: object) -> str:
    normalized = asset_url_identity(value)
    return normalized[0] if normalized else str(value)


def invalid_primary_asset_evidence(evidence: Evidence) -> bool:
    if not is_utility_image_url(evidence.value):
        return False
    path = urlsplit(str(evidence.value or "")).path.rsplit("/", 1)[-1]
    structured_image_relationship = (
        evidence.collector_id in {"jsonld", "opengraph", "microdata"}
        and evidence.relation_type in {"product_asset", "variant_asset"}
        and "image" in evidence.locator.value.casefold()
    )
    return not (
        structured_image_relationship
        and "." not in path
        and structured_extensionless_image_url(evidence.value)
    )


def accepted_asset_evidence(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
) -> Evidence | None:
    candidates = [
        evidence_by_id[eid] for eid in asset.url_evidence_ids if eid in evidence_by_id
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            int(invalid_primary_asset_evidence(row)),
            int(public_asset_delivery_url(row.value) is None),
            int(urlsplit(str(row.value)).scheme.casefold() != "https"),
            -_requested_dimension(row.value),
            rank(row),
        ),
    )


def asset_rank(
    asset: AssetEntity,
    accepted: Evidence | None,
) -> tuple[int, int, int, int, tuple[object, ...], str]:
    if accepted is None:
        return (99, 99, 99, 99, (99, 99, 99, 0.0, ""), asset.entity_id)
    return (
        _role_rank(str(accepted.value)),
        _collector_rank(accepted),
        _source_order(accepted),
        int(urlsplit(str(accepted.value)).scheme.casefold() != "https"),
        rank(accepted),
        asset.entity_id,
    )


def resolve_product_assets(
    assets: tuple[AssetEntity, ...],
    evidence_by_id: dict[str, Evidence],
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
    *,
    variants: tuple[VariantEntity, ...] = (),
    variant_decisions: tuple[VariantDecision, ...] = (),
) -> tuple[AssetDecision, ...]:
    evaluated = _evaluated_parent_assets(
        assets,
        evidence_by_id,
        conflicting_urls=conflicting_urls,
        low_resolution_urls=low_resolution_urls,
    )
    valid = [row for row in evaluated if not row[3]]
    valid.sort(key=lambda item: item[0])
    decisions = _accepted_asset_decisions(valid)
    rejected = _rejected_asset_decisions(evaluated, valid_count=len(valid))
    if decisions:
        return tuple((*decisions, *rejected))
    fallback = _variant_parent_fallback(
        assets,
        variants,
        variant_decisions,
        evidence_by_id,
        conflicting_urls=conflicting_urls,
        low_resolution_urls=low_resolution_urls,
    )
    return tuple((*fallback, *rejected))


def _evaluated_parent_assets(
    assets: tuple[AssetEntity, ...],
    evidence_by_id: dict[str, Evidence],
    *,
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> list[tuple[tuple, AssetEntity, Evidence, tuple[str, ...]]]:
    ranked = [
        (asset_rank(asset, accepted), asset, accepted)
        for asset in assets
        if asset.variant_entity_id is None
        if (accepted := accepted_asset_evidence(asset, evidence_by_id)) is not None
    ]
    return [
        (
            rank_value,
            asset,
            accepted,
            _rejection_reasons(
                _delivery_url(accepted),
                evidence=accepted,
                conflicting_urls=conflicting_urls,
                low_resolution_urls=low_resolution_urls,
            ),
        )
        for rank_value, asset, accepted in ranked
    ]


def _accepted_asset_decisions(
    valid: list[tuple[tuple, AssetEntity, Evidence, tuple[str, ...]]],
) -> list[AssetDecision]:
    decisions: list[AssetDecision] = []
    seen_identity: set[str] = set()
    seen_delivery: set[str] = set()
    for index, (_rank_value, asset, accepted, _reasons) in enumerate(valid):
        if len(decisions) >= PRODUCT_ASSET_MAX_COUNT:
            break
        delivery_url = _delivery_url(accepted)
        delivery_identity = _delivery_identity(delivery_url)
        if asset.identity_key in seen_identity or delivery_identity in seen_delivery:
            continue
        seen_identity.add(asset.identity_key)
        seen_delivery.add(delivery_identity)
        primary = not decisions
        decisions.append(
            AssetDecision(
                asset_entity_id=asset.entity_id,
                url=delivery_url,
                accepted_evidence_ids=(accepted.evidence_id,),
                role="primary" if primary else "additional",
                rank=index,
                rule_id="PRODUCT_ASSET_PRIMARY"
                if primary
                else "PRODUCT_ASSET_ADDITIONAL",
            )
        )
    return decisions


def _rejected_asset_decisions(
    evaluated: list[tuple[tuple, AssetEntity, Evidence, tuple[str, ...]]],
    *,
    valid_count: int,
) -> list[AssetDecision]:
    return [
        AssetDecision(
            asset_entity_id=asset.entity_id,
            url=_delivery_url(accepted),
            accepted_evidence_ids=(),
            role="rejected",
            rank=valid_count + index,
            rule_id="PRODUCT_ASSET_REJECT",
            rejection_reasons=reasons,
        )
        for index, (_rank_value, asset, accepted, reasons) in enumerate(evaluated)
        if reasons
    ]


def _variant_parent_fallback(
    assets: tuple[AssetEntity, ...],
    variants: tuple[VariantEntity, ...],
    variant_decisions: tuple[VariantDecision, ...],
    evidence_by_id: dict[str, Evidence],
    *,
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> tuple[AssetDecision, ...]:
    eligible_ids = {
        row.variant_entity_id for row in variant_decisions if row.status == "eligible"
    }
    selected_ids = {
        row.entity_id
        for row in variants
        if row.selected and row.entity_id in eligible_ids
    }
    candidates = _eligible_variant_assets(
        assets,
        evidence_by_id,
        eligible_ids=eligible_ids,
        conflicting_urls=conflicting_urls,
        low_resolution_urls=low_resolution_urls,
    )
    allowed_ids = _fallback_owner_ids(candidates, selected_ids=selected_ids)
    if not allowed_ids:
        return ()
    candidates = [row for row in candidates if row[1].variant_entity_id in allowed_ids]
    if not candidates:
        return ()
    _rank_value, asset, accepted = min(candidates, key=lambda item: item[0])
    return (
        AssetDecision(
            asset_entity_id=asset.entity_id,
            url=_delivery_url(accepted),
            accepted_evidence_ids=(accepted.evidence_id,),
            role="primary",
            rank=0,
            rule_id="VARIANT_ASSET_PARENT_FALLBACK",
        ),
    )


def _eligible_variant_assets(
    assets: tuple[AssetEntity, ...],
    evidence_by_id: dict[str, Evidence],
    *,
    eligible_ids: set[str],
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> list[tuple[tuple, AssetEntity, Evidence]]:
    return [
        (asset_rank(asset, accepted), asset, accepted)
        for asset in assets
        if asset.variant_entity_id in eligible_ids
        if (accepted := accepted_asset_evidence(asset, evidence_by_id)) is not None
        if not _rejection_reasons(
            _delivery_url(accepted),
            evidence=accepted,
            conflicting_urls=conflicting_urls,
            low_resolution_urls=low_resolution_urls,
        )
    ]


def _fallback_owner_ids(
    candidates: list[tuple[tuple, AssetEntity, Evidence]],
    *,
    selected_ids: set[str],
) -> set[str]:
    owners = {
        asset.variant_entity_id
        for _rank, asset, _accepted in candidates
        if asset.variant_entity_id is not None
    }
    if len(selected_ids) == 1:
        return selected_ids
    return owners if len(owners) == 1 else set()


def _rejection_reasons(
    url: str,
    *,
    evidence: Evidence,
    conflicting_urls: frozenset[str],
    low_resolution_urls: frozenset[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not url:
        reasons.append("invalid_asset_delivery_url")
    if url in conflicting_urls:
        reasons.append("product_identity_conflict")
    if url in low_resolution_urls:
        reasons.append("low_resolution_transform")
    if invalid_primary_asset_evidence(evidence):
        reasons.append("invalid_primary_asset")
    return tuple(reasons)


def _delivery_url(evidence: Evidence) -> str:
    return public_asset_delivery_url(evidence.value) or ""


def _delivery_identity(value: object) -> str:
    normalized = asset_url_identity(value)
    return normalized[1] if normalized else str(value)


def _requested_dimension(value: object) -> int:
    return max(
        (
            int(raw_value)
            for key, raw_value in parse_qsl(
                urlsplit(str(value or "")).query, keep_blank_values=False
            )
            if key.casefold() in IMAGE_DIMENSION_QUERY_KEYS and str(raw_value).isdigit()
        ),
        default=0,
    )


def _role_rank(url: str) -> int:
    text = str(url or "").casefold()
    if any(token in text for token in ("main", "primary", "hero", "pdp")):
        return 0
    if any(token in text for token in ("product", "detail", "gallery", "diagram")):
        return 1
    return 2


def _source_order(evidence: Evidence) -> int:
    tokens = str(evidence.locator.value or "").replace("[", "/").replace("]", "")
    return next(
        (int(token) for token in reversed(tokens.split("/")) if token.isdigit()), 99
    )


def _collector_rank(evidence: Evidence) -> int:
    return {
        "jsonld": 0,
        "opengraph": 1,
        "microdata": 2,
        "dom": 3,
        "css_recipe": 3,
        "js_state": 4,
        "network": 5,
        "url": 6,
    }.get(evidence.collector_id, 9)
