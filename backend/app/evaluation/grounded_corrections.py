from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.extraction_memory import (
    EXTRACTION_CORRECTION_STATUS_ACTIVATED,
    EXTRACTION_CORRECTION_STATUS_REPLAY_FAILED,
    EXTRACTION_CORRECTION_STATUS_REPLAY_PASSED,
    EXTRACTION_LABEL_KIND_GROUNDED_CORRECTION,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.core.db_utils import mapping_or_empty
from app.core.domain_utils import normalize_domain
from app.core.records.field_policy import normalize_field_key
from app.core.shared.field_coerce import object_list, safe_int
from app.evaluation.schema import GroundedLabel
from app.extraction.documents import DocumentStore
from app.models.crawl_run import CrawlRun, CrawlUrlResult
from app.models.extraction_memory import (
    ExtractionManifest,
    ExtractionOperatorLabel,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.persistence.artifacts import ArtifactRepository
from app.persistence.extraction_memory import (
    activate_release_snapshot_for_run,
    create_candidate_release_snapshot,
    upsert_recipe,
)

logger = logging.getLogger(__name__)


class GroundedCorrectionScopeMismatch(ValueError):
    """Grounded correction replay passed for a template outside the run scope."""


# Only human truth or qualified deterministic pseudo-labels may activate a rule.
# Weak and unverified-model authorities (grounded LLM repair) can be compiled and
# replayed for review but must never flip an active release.
_ACTIVATION_AUTHORITIES = frozenset({"human_verified", "deterministic_pseudo"})


def _authority_can_activate(authority: str) -> bool:
    return authority in _ACTIVATION_AUTHORITIES


async def save_grounded_correction(
    session: AsyncSession,
    *,
    run: CrawlRun,
    labels: list[dict[str, object]],
    activate: bool = False,
    representative_url_result_ids: list[int] | None = None,
    authority: str = "human_verified",
) -> dict[str, object]:
    domain = normalize_domain(run.url)
    grounded_labels = _grounded_labels(labels, run=run, authority=authority)
    proposal = _candidate_recipe_proposal(grounded_labels, source_run_id=run.id)
    replay = await _evaluate_representative_replay(
        session,
        run=run,
        labels=grounded_labels,
        proposal=proposal,
        representative_url_result_ids=representative_url_result_ids or [],
    )
    status_name = _replay_status(replay)
    if activate and replay["passed"] and _authority_can_activate(authority):
        release = await _activate_grounded_correction(
            session,
            run=run,
            domain=domain,
            proposal=proposal,
            replay=replay,
        )
        replay["release_snapshot_id"] = str(release.id)
        status_name = EXTRACTION_CORRECTION_STATUS_ACTIVATED
    label = ExtractionOperatorLabel(
        label_kind=EXTRACTION_LABEL_KIND_GROUNDED_CORRECTION,
        source_run_id=run.id,
        template_id=_optional_uuid(replay.get("template_id")),
        domain=domain,
        surface=run.surface,
        action=status_name,
        payload={
            "labels": [row.model_dump(mode="json") for row in grounded_labels],
            "proposal": proposal,
            "replay": replay,
            "activation_requested": bool(activate),
            "activation_status": status_name,
        },
    )
    session.add(label)
    await session.commit()
    await session.refresh(label)
    return {
        "correction_id": label.id,
        "domain": domain,
        "surface": run.surface,
        "label_count": len(grounded_labels),
        "activation_status": status_name,
        "replay": replay,
    }


def _grounded_labels(
    payloads: list[dict[str, object]],
    *,
    run: CrawlRun,
    authority: str = "human_verified",
) -> list[GroundedLabel]:
    # Only human-verified labels may carry verifier metadata (see GroundedLabel);
    # model/weak labels stay unstamped and never become release-eligible.
    verifier = (
        {"verifier_id": str(run.user_id), "verified_at": datetime.now(UTC)}
        if authority == "human_verified"
        else {}
    )
    return [
        GroundedLabel.model_validate(
            {
                **dict(payload),
                "label_id": f"run-{run.id}-{uuid4()}",
                "authority": authority,
                **verifier,
            }
        )
        for payload in payloads
    ]


def _replay_status(replay: dict[str, object]) -> str:
    return (
        EXTRACTION_CORRECTION_STATUS_REPLAY_PASSED
        if replay["passed"]
        else EXTRACTION_CORRECTION_STATUS_REPLAY_FAILED
    )


async def _evaluate_representative_replay(
    session: AsyncSession,
    *,
    run: CrawlRun,
    labels: list[GroundedLabel],
    proposal: dict[str, object],
    representative_url_result_ids: list[int],
) -> dict[str, object]:
    representative_ids = _representative_ids(representative_url_result_ids)
    base = _replay_summary(labels, representative_ids)
    rules = _selector_rules(proposal.get("selector_rules"))
    invalid = _invalid_replay(base, labels=labels, proposal=proposal, rules=rules)
    if invalid is not None:
        return invalid
    url_results, template_id, cohort_error = await _load_replay_cohort(
        session, run=run, representative_ids=representative_ids, base=base
    )
    if cohort_error is not None:
        return cohort_error
    checks, artifact_error = _replay_artifacts(
        run=run,
        url_results=url_results,
        rules=rules,
        base=base,
    )
    if artifact_error is not None:
        return artifact_error
    return {
        **base,
        "passed": True,
        "reason": "representative_replay_passed",
        "template_id": str(template_id),
        "checks": checks,
    }


def _representative_ids(values: list[int]) -> list[int]:
    return sorted(
        {
            parsed
            for value in values
            if (parsed := safe_int(value)) is not None and parsed > 0
        }
    )


def _invalid_replay(
    base: dict[str, object],
    *,
    labels: list[GroundedLabel],
    proposal: dict[str, object],
    rules: list[dict[str, object]],
) -> dict[str, object] | None:
    if not labels:
        return _failure(base, "grounded_labels_required")
    if proposal.get("conflicts"):
        return _failure(base, "conflicting_grounded_selectors")
    if not rules:
        return _failure(base, "css_grounding_required")
    if not base["representative_url_result_ids"]:
        return _failure(base, "representative_replay_required")
    return None


async def _load_replay_cohort(
    session: AsyncSession,
    *,
    run: CrawlRun,
    representative_ids: list[int],
    base: dict[str, object],
) -> tuple[list[CrawlUrlResult], UUID | None, dict[str, object] | None]:
    url_results = list(
        (
            await session.execute(
                select(CrawlUrlResult).where(
                    CrawlUrlResult.run_id == run.id,
                    CrawlUrlResult.id.in_(representative_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    found_ids = {row.id for row in url_results}
    missing_ids = sorted(set(representative_ids) - found_ids)
    if missing_ids:
        return (
            [],
            None,
            _failure(
                base,
                "representative_results_not_owned_by_run",
                missing_url_result_ids=missing_ids,
            ),
        )
    manifests = list(
        (
            await session.execute(
                select(ExtractionManifest).where(
                    ExtractionManifest.run_id == run.id,
                    ExtractionManifest.url_result_id.in_(representative_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    manifest_ids = {row.url_result_id for row in manifests}
    missing_manifest_ids = sorted(set(representative_ids) - manifest_ids)
    template_ids = {row.template_id for row in manifests if row.template_id is not None}
    if missing_manifest_ids or len(template_ids) != 1:
        return (
            [],
            None,
            _failure(
                base,
                "representative_template_cohort_required",
                missing_manifest_url_result_ids=missing_manifest_ids,
                template_ids=sorted(str(value) for value in template_ids),
            ),
        )
    return url_results, next(iter(template_ids)), None


def _replay_artifacts(
    *,
    run: CrawlRun,
    url_results: list[CrawlUrlResult],
    rules: list[dict[str, object]],
    base: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    repository = ArtifactRepository(root_dir=settings.artifacts_dir)
    checks: list[dict[str, object]] = []
    for url_result in sorted(url_results, key=lambda row: row.id):
        artifact_uri = f"runs/{run.id}/results/{url_result.id}/page.html"
        try:
            html = repository.read_text(artifact_uri)
        except (OSError, ValueError):
            return checks, _failure(
                base,
                "representative_artifact_missing",
                failed_url_result_id=url_result.id,
                artifact_uri=artifact_uri,
                checks=checks,
            )
        document = DocumentStore({"html": html}).html("html")
        for rule in rules:
            check, reason = _replay_rule(document, url_result.id, rule)
            checks.append(check)
            if reason:
                return checks, _failure(
                    base,
                    reason,
                    failed_url_result_id=url_result.id,
                    field_name=check["field_name"],
                    css_selector=check["css_selector"],
                    checks=checks,
                )
    return checks, None


def _replay_rule(document, url_result_id: int, rule: dict[str, object]):
    field_name = normalize_field_key(str(rule.get("field_name") or ""))
    selector = str(rule.get("css_selector") or "").strip()
    try:
        nodes = document.css(selector)
    except Exception:
        logger.debug(
            "Grounded selector %r for field %r failed to evaluate",
            selector,
            field_name,
            exc_info=True,
        )
        return _check(
            url_result_id, field_name, selector, 0
        ), "invalid_grounded_selector"
    check = _check(url_result_id, field_name, selector, len(nodes))
    if len(nodes) != 1 or not _node_has_value(nodes[0]):
        return check, "grounded_selector_replay_failed"
    return check, None


def _check(
    url_result_id: int, field_name: str, selector: str, match_count: int
) -> dict[str, object]:
    return {
        "url_result_id": url_result_id,
        "field_name": field_name,
        "css_selector": selector,
        "match_count": match_count,
    }


async def _activate_grounded_correction(
    session: AsyncSession,
    *,
    run: CrawlRun,
    domain: str,
    proposal: dict[str, object],
    replay: dict[str, object],
) -> ExtractionReleaseSnapshot:
    template_id = _optional_uuid(replay.get("template_id"))
    template = (
        await session.get(ExtractionTemplate, template_id) if template_id else None
    )
    if template is None or template.domain != domain or template.surface != run.surface:
        raise GroundedCorrectionScopeMismatch(
            "Representative replay template does not match the run scope."
        )
    existing_recipe = (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS,
            )
        )
    ).scalar_one_or_none()
    existing_rules = _selector_rules(
        mapping_or_empty(existing_recipe.payload).get("rules")
        if existing_recipe is not None
        else []
    )
    correction_rules = _selector_rules(proposal.get("selector_rules"))
    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload={"rules": _merge_rules(existing_rules, correction_rules)},
    )
    candidate = await create_candidate_release_snapshot(
        session, domain=domain, surface=run.surface
    )
    return await activate_release_snapshot_for_run(
        session, run_id=run.id, release_snapshot_id=candidate.id
    )


def _merge_rules(
    existing_rules: list[dict[str, object]],
    correction_rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    corrected_fields = {
        normalize_field_key(str(row.get("field_name") or ""))
        for row in correction_rules
    }
    return [
        row
        for row in existing_rules
        if normalize_field_key(str(row.get("field_name") or "")) not in corrected_fields
    ] + correction_rules


def _replay_summary(
    labels: list[GroundedLabel], representative_ids: list[int]
) -> dict[str, object]:
    return {
        "representative_url_result_ids": representative_ids,
        "label_target_kinds": sorted({label.target_kind for label in labels}),
        "field_names": sorted(
            {
                str(label.field_name)
                for label in labels
                if label.target_kind in {"field", "explicit_absence"}
                and label.field_name
            }
        ),
    }


def _candidate_recipe_proposal(
    labels: list[GroundedLabel], *, source_run_id: int
) -> dict[str, object]:
    rules_by_selector: dict[tuple[str, str], dict[str, object]] = {}
    selectors_by_field: dict[str, set[str]] = {}
    for label in labels:
        if label.target_kind != "field" or not label.field_name:
            continue
        field_name = normalize_field_key(label.field_name)
        for reference in label.grounding:
            locator = str(reference.locator or "").strip()
            if reference.kind not in {"node", "path"} or not locator.startswith("css:"):
                continue
            selector = locator.removeprefix("css:").strip()
            if not selector:
                continue
            selectors_by_field.setdefault(field_name, set()).add(selector)
            key = (field_name, selector)
            rule = rules_by_selector.get(key)
            if rule is None:
                rules_by_selector[key] = {
                    "field_name": field_name,
                    "css_selector": selector,
                    "source": "grounded_correction",
                    "source_run_id": source_run_id,
                    "status": "validated",
                    "is_active": True,
                    "semantic_role": label.semantic_role,
                    "locale_interpretation": label.locale_interpretation,
                }
                continue
            if rule.get("semantic_role") is None and label.semantic_role is not None:
                rule["semantic_role"] = label.semantic_role
            if (
                rule.get("locale_interpretation") is None
                and label.locale_interpretation is not None
            ):
                rule["locale_interpretation"] = label.locale_interpretation
    conflicts = [
        {"field_name": field_name, "selectors": sorted(selectors)}
        for field_name, selectors in selectors_by_field.items()
        if len(selectors) > 1
    ]
    return {
        "selector_rules": list(rules_by_selector.values()),
        "conflicts": conflicts,
        "label_count": len(labels),
    }


def _selector_rules(value: object) -> list[dict[str, object]]:
    return [dict(row) for row in object_list(value) if isinstance(row, dict)]


def _node_has_value(node) -> bool:
    for attribute in ("content", "value", "href", "src", "alt", "title", "aria-label"):
        if str(node.attribute(attribute) or "").strip():
            return True
    return bool(" ".join(node.text(separator=" ", strip=True).split()))


def _failure(
    base: dict[str, object], reason: str, **details: object
) -> dict[str, object]:
    return {**base, "passed": False, "reason": reason, **details}


def _optional_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None
