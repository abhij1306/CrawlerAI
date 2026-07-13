from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.extraction_memory import (
    EXTRACTION_CORRECTION_STATUS_ACTIVATED,
    EXTRACTION_CORRECTION_STATUS_REPLAY_FAILED,
    EXTRACTION_CORRECTION_STATUS_REPLAY_PASSED,
    EXTRACTION_LABEL_KIND_GROUNDED_CORRECTION,
)
from app.core.domain_utils import normalize_domain
from app.core.shared.field_coerce import object_list, safe_int
from app.core.extraction_memory.recipe_contracts import RecipeCandidate
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface
from app.models.crawl_run import CrawlRun, CrawlUrlResult
from app.models.extraction_memory import (
    ExtractionManifest,
    ExtractionOperatorLabel,
    ExtractionTemplate,
)
from app.persistence.artifacts import ArtifactRepository
from app.persistence.extraction_memory import (
    activate_release_snapshot_for_run,
)
from app.persistence.extraction_recipe_lifecycle import (
    create_executable_release_snapshot,
    record_candidate_validation,
    save_recipe_candidate,
)


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
    recipe_candidate: RecipeCandidate | None = None,
    activate: bool = False,
    representative_url_result_ids: list[int] | None = None,
    authority: str = "human_verified",
) -> dict[str, object]:
    if recipe_candidate is None:
        raise ValueError(
            "recipe_candidate is required; selector corrections are retired"
        )
    return await _save_grounded_recipe_correction(
        session,
        run=run,
        candidate=recipe_candidate,
        activate=activate,
        representative_url_result_ids=representative_url_result_ids or [],
        authority=authority,
    )


async def _save_grounded_recipe_correction(
    session: AsyncSession,
    *,
    run: CrawlRun,
    candidate: RecipeCandidate,
    activate: bool,
    representative_url_result_ids: list[int],
    authority: str,
) -> dict[str, object]:
    domain = normalize_domain(run.url)
    replay = await _evaluate_recipe_candidate_replay(
        session,
        run=run,
        candidate=candidate,
        representative_url_result_ids=representative_url_result_ids,
    )
    status_name = _replay_status(replay)
    if activate and replay["passed"] and _authority_can_activate(authority):
        template = await session.get(
            ExtractionTemplate, _optional_uuid(replay.get("template_id"))
        )
        if (
            template is None
            or template.domain != domain
            or template.surface != run.surface
        ):
            raise GroundedCorrectionScopeMismatch(
                "Representative replay template does not match the run scope."
            )
        _recipe, compiled = await save_recipe_candidate(
            session, template=template, candidate=candidate
        )
        for sample_url in object_list(replay.get("sample_urls")):
            await record_candidate_validation(
                session,
                compiled=compiled,
                sample_url=str(sample_url),
                succeeded=True,
                explicit_approval=True,
            )
        release = await create_executable_release_snapshot(
            session, domain=domain, surface=run.surface
        )
        await activate_release_snapshot_for_run(
            session, run_id=run.id, release_snapshot_id=release.id
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
            "recipe_candidate": candidate.model_dump(mode="json"),
            "replay": replay,
            "activation_requested": activate,
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
        "label_count": 0,
        "activation_status": status_name,
        "replay": replay,
    }


async def _evaluate_recipe_candidate_replay(
    session: AsyncSession,
    *,
    run: CrawlRun,
    candidate: RecipeCandidate,
    representative_url_result_ids: list[int],
) -> dict[str, object]:
    representative_ids = _representative_ids(representative_url_result_ids)
    base: dict[str, object] = {
        "passed": False,
        "representative_url_result_ids": representative_ids,
        "checks": [],
        "sample_urls": [],
    }
    if not representative_ids:
        return _failure(base, "representative_replay_required")
    url_results, template_id, failure = await _load_replay_cohort(
        session,
        run=run,
        representative_ids=representative_ids,
        base=base,
    )
    if failure is not None:
        return failure
    repository = ArtifactRepository(root_dir=settings.artifacts_dir)
    checks: list[dict[str, object]] = []
    sample_urls: list[str] = []
    for url_result in sorted(url_results, key=lambda row: row.id):
        artifact_uri = f"runs/{run.id}/results/{url_result.id}/page.html"
        try:
            html = repository.read_text(artifact_uri)
        except (OSError, ValueError):
            return _failure(base, "representative_artifact_missing")
        page_url = url_result.final_url or url_result.requested_url
        request = fixture_request_from_inputs(
            Surface(run.surface), html, page_url, max_records=1
        )
        execution = execute_recipe(request, candidate.recipe)
        check: dict[str, object] = {
            "url_result_id": url_result.id,
            "failure_code": execution.failure_code,
            "record_count": len(execution.records),
        }
        checks.append(check)
        sample_urls.append(page_url)
        if execution.failure_code is not None or not execution.records:
            return _failure(
                base,
                "recipe_candidate_replay_failed",
                checks=checks,
                failed_url_result_id=url_result.id,
            )
    return {
        **base,
        "passed": True,
        "template_id": str(template_id),
        "checks": checks,
        "sample_urls": sample_urls,
    }


def _replay_status(replay: dict[str, object]) -> str:
    return (
        EXTRACTION_CORRECTION_STATUS_REPLAY_PASSED
        if replay["passed"]
        else EXTRACTION_CORRECTION_STATUS_REPLAY_FAILED
    )


def _representative_ids(values: list[int]) -> list[int]:
    return sorted(
        {
            parsed
            for value in values
            if (parsed := safe_int(value)) is not None and parsed > 0
        }
    )


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


def _failure(
    base: dict[str, object], reason: str, **details: object
) -> dict[str, object]:
    return {**base, "passed": False, "reason": reason, **details}


def _optional_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None
