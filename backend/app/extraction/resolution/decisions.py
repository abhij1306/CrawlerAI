"""Scalar/asset decision machinery: admissibility, ranking, rejection."""
from __future__ import annotations

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_TITLE_MEASUREMENT_FLAG,
    DETAIL_TITLE_REJECTION_FLAGS,
    INVALID_AVAILABILITY_EVIDENCE_FLAG,
    VARIANT_COLOR_BRAND_CONFLICT_FLAG,
)
from app.core.config.field_mappings import INVALID_SCALAR_TYPE_EVIDENCE_FLAG
from app.core.records.url_identity import detail_url_resource_identity
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    AssetDecision,
    Decision,
    DerivedFact,
    Evidence,
    Finding,
    RejectedEvidence,
)
from app.extraction.entities import AssetEntity
from app.extraction.resolution.assets import (
    accepted_asset_evidence,
    invalid_primary_asset_evidence,
)
from app.extraction.resolution.lineage import _aggregate_fact
from app.extraction.resolution.ranking import non_positive_money, rank



def _asset_publication_facts(
    asset_decisions: tuple[AssetDecision, ...],
    decisions: tuple[Decision, ...],
) -> tuple[DerivedFact, ...]:
    selected_by_entity = {
        row.entity_id: row
        for row in decisions
        if row.fact_type == field_mappings.ASSET_IMAGE_URL_FACT_TYPE
        and row.status == "resolved"
        and row.accepted_evidence_ids
    }
    facts: list[DerivedFact] = []
    for asset in asset_decisions:
        if (
            not asset.asset_entity_id
            or not asset.url
            or not asset.accepted_evidence_ids
        ):
            continue
        selected = selected_by_entity.get(asset.asset_entity_id)
        selected_fact_ids = (
            (stable_id("selected", selected.decision_id),) if selected else ()
        )
        for fact_type, value in (
            ("asset.inclusion", True),
            ("asset.role", asset.role),
            ("asset.position", asset.rank),
        ):
            facts.append(
                _aggregate_fact(
                    asset.asset_entity_id,
                    fact_type,
                    value,
                    asset.accepted_evidence_ids,
                    asset.rule_id,
                    input_selected_fact_ids=selected_fact_ids,
                )
            )
    return tuple(facts)

def _url_mismatched_product_subjects(
    evidence: tuple[Evidence, ...],
) -> frozenset[str]:
    title_flags_by_subject: dict[str, set[str]] = {}
    target_url_identities = {
        identity
        for row in evidence
        if row.collector_id == "url" and row.fact_type == "product.url"
        if (identity := detail_url_resource_identity(str(row.value)))
    }
    url_confirmed_subjects = {
        row.subject_id
        for row in evidence
        if row.subject_id
        and row.fact_type == "product.url"
        and detail_url_resource_identity(str(row.value)) in target_url_identities
    }
    for row in evidence:
        if (
            row.fact_type != field_mappings.PRODUCT_TITLE_FACT_TYPE
            or not row.subject_id
        ):
            continue
        title_flags_by_subject.setdefault(row.subject_id, set()).update(row.flags)
    return frozenset(
        subject_id
        for subject_id, flags in title_flags_by_subject.items()
        if "title_url_mismatch" in flags
        and "title_url_match" not in flags
        and subject_id not in url_confirmed_subjects
    )

def _resolve_asset(
    asset: AssetEntity,
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
) -> Decision:
    # Missing evidence is invalid, so an asset cannot resolve from dangling IDs.
    invalid_ids = tuple(
        eid
        for eid in asset.url_evidence_ids
        if eid not in evidence_by_id
        or invalid_primary_asset_evidence(evidence_by_id[eid])
    )
    valid_ids = tuple(
        eid
        for eid in asset.url_evidence_ids
        if eid in evidence_by_id
        and not invalid_primary_asset_evidence(evidence_by_id[eid])
    )
    if invalid_ids and not valid_ids:
        return Decision(
            decision_id=stable_id(
                "decision",
                asset.entity_id,
                field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
                asset.url_evidence_ids,
            ),
            entity_id=asset.entity_id,
            fact_type=field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
            accepted_evidence_ids=(),
            rejected=tuple(
                RejectedEvidence(evidence_id=eid, reason="invalid_primary_asset")
                for eid in asset.url_evidence_ids
            ),
            finding_ids=(),
            rule_id="PRIMARY_ASSET_REJECTION",
            status="unresolved",
        )
    preferred = accepted_asset_evidence(asset, evidence_by_id)
    decision = _resolve_scalar(
        asset.entity_id,
        field_mappings.ASSET_IMAGE_URL_FACT_TYPE,
        valid_ids,
        evidence_by_id,
        findings,
        preferred_evidence_ids=(preferred.evidence_id,) if preferred else (),
    )
    if preferred and decision.accepted_evidence_ids == (preferred.evidence_id,):
        return decision.model_copy(update={"rule_id": "ASSET_DELIVERY_QUALITY"})
    return decision

def _resolve_scalar(
    entity_id: str,
    fact_type: str,
    ids: tuple[str, ...],
    evidence_by_id: dict[str, Evidence],
    findings: tuple[Finding, ...],
    *,
    preferred_evidence_ids: tuple[str, ...] = (),
) -> Decision:
    candidates = sorted(
        (evidence_by_id[eid] for eid in ids if eid in evidence_by_id), key=rank
    )
    blocking = {
        eid for finding in findings if finding.blocking for eid in finding.evidence_ids
    }
    admissible = [
        ev
        for ev in candidates
        if ev.evidence_id not in blocking and _invalidity_reason(ev) is None
    ]
    finding_ids = tuple(
        f.finding_id for f in findings if set(f.evidence_ids) & set(ids)
    )
    if not admissible:
        return Decision(
            decision_id=stable_id("decision", entity_id, fact_type, ids),
            entity_id=entity_id,
            fact_type=fact_type,
            accepted_evidence_ids=(),
            # Preserve the concrete rejection reason for diagnostics.
            rejected=tuple(
                RejectedEvidence(
                    evidence_id=ev.evidence_id,
                    reason="blocked_by_finding"
                    if ev.evidence_id in blocking
                    else (_invalidity_reason(ev) or "invalid_value"),
                )
                for ev in candidates
            ),
            finding_ids=finding_ids,
            rule_id="SCALAR_LEXICOGRAPHIC",
            status="unresolved",
        )
    preferred = set(preferred_evidence_ids)
    winner = next(
        (row for row in admissible if row.evidence_id in preferred), admissible[0]
    )
    rule_id = (
        "CONTRACT_PREFERRED_SOURCE"
        if winner.evidence_id in preferred
        else "SCALAR_LEXICOGRAPHIC"
    )
    if fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        rule_id = (
            "TITLE_URL_REVIEW_ONLY"
            if "url_derived_title" in winner.flags
            else "TITLE_SEMANTIC_RANKING"
        )

    def _rejected_reason(ev: Evidence) -> str:
        if ev.evidence_id in blocking:
            return "blocked_by_finding"
        reason = _invalidity_reason(ev)
        if reason is not None:
            return reason
        return (
            "stable_tiebreak"
            if rank(ev)[:-1] == rank(winner)[:-1]
            else "lower_confidence"
        )

    return Decision(
        decision_id=stable_id("decision", entity_id, fact_type, winner.evidence_id),
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=(winner.evidence_id,),
        rejected=tuple(
            RejectedEvidence(
                evidence_id=ev.evidence_id,
                reason=_rejected_reason(ev),
            )
            for ev in candidates
            if ev.evidence_id != winner.evidence_id
        ),
        finding_ids=finding_ids,
        rule_id=rule_id,
        status="resolved",
    )

_GENERIC_INVALIDITY_FLAGS = frozenset(
    {
        "ambiguous_page_price",
        "brand_boilerplate",
        "brand_identity_conflict",
        "brand_url",
        "category_as_brand",
        "description_incomplete_ending",
        "description_missing_separator",
        "description_promotional_copy",
        "description_ui_pollution",
        "invalid_decimal",
        "invalid_currency",
        "invalid_brand_scalar",
        "non_manufacturer_brand_role",
        INVALID_AVAILABILITY_EVIDENCE_FLAG,
        INVALID_SCALAR_TYPE_EVIDENCE_FLAG,
        "invalid_gtin",
        "non_detail_product_url",
        "product_name_as_brand",
        DETAIL_TITLE_MEASUREMENT_FLAG,
        "placeholder_text",
        "tracking_url",
        VARIANT_COLOR_BRAND_CONFLICT_FLAG,
    }
)

def _invalidity_reason(ev: Evidence) -> str | None:
    """Return the concrete rejection reason, or ``None`` when admissible."""

    if ev.fact_type in {
        field_mappings.OFFER_PRICE_FACT_TYPE,
        field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    } and non_positive_money(ev.value):
        return "non_positive_price"
    flags = set(ev.flags)
    title_rejections = flags & (DETAIL_TITLE_REJECTION_FLAGS - {"truncated_title"})
    if ev.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE and title_rejections:
        return min(title_rejections)
    description_rejections = flags & {
        "description_truncated_ellipsis",
        "description_truncated_fragment",
    }
    if ev.fact_type == "product.description" and description_rejections:
        return min(description_rejections)
    generic = flags & _GENERIC_INVALIDITY_FLAGS
    if generic:
        return min(generic)
    return None
