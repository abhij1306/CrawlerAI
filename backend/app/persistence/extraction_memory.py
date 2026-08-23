from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_MEMORY_STATUS_TRUSTED,
    EXTRACTION_MEMORY_STATUS_PROVISIONAL,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_EXECUTABLE,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    EXTRACTION_RECIPE_OWNERSHIP_LABEL_KINDS,
)
from app.core.domain_utils import normalize_domain
from app.core.config.cascade import (
    CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS,
    CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS,
)
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_route,
)
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionManifest,
    ExtractionObservation,
    ExtractionOperatorLabel,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.persistence.extraction_memory_sources import (
    merge_observed_contracts,
    observed_field_sources,
)
from app.persistence.extraction_memory_releases import (
    RecipeCompileError,
    activate_release_snapshot_for_run,
    active_release_snapshot_for_run,
    build_release_payload,
    compile_recipe_layers,
    create_candidate_release_snapshot,
    create_release_snapshot,
    load_release_payload,
    reset_release_payload_cache,
    rollback_release_snapshot_for_run,
    selector_rules_from_release,
)
from app.persistence.extraction_memory_observations import (
    record_sentinel_observations,
)

__all__ = [
    "RecipeCompileError",
    "activate_release_snapshot_for_run",
    "active_release_snapshot_for_run",
    "build_release_payload",
    "compile_recipe_layers",
    "create_candidate_release_snapshot",
    "create_release_snapshot",
    "load_release_payload",
    "reset_release_payload_cache",
    "rollback_release_snapshot_for_run",
    "selector_rules_from_release",
]

if TYPE_CHECKING:
    from app.extraction.contracts import ExtractionResult


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def ensure_template(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    fingerprint: str,
    route_pattern: str = "",
    tech_signals: list[str] | None = None,
    run_id: int | None = None,
) -> ExtractionTemplate:
    normalized_domain = str(domain or "").strip().lower()
    row = (
        await session.execute(
            select(ExtractionTemplate).where(
                ExtractionTemplate.domain == normalized_domain,
                ExtractionTemplate.surface == surface,
                ExtractionTemplate.fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ExtractionTemplate(
            domain=normalized_domain,
            surface=surface,
            fingerprint=fingerprint,
            route_pattern=route_pattern,
            tech_signals=list(tech_signals or []),
            last_seen_run_id=run_id,
        )
        try:
            # Concurrency-safe insert: a racing worker may create the same
            # (domain, surface, fingerprint) row between the SELECT above and
            # this flush. The unique index turns that into an IntegrityError we
            # recover from by re-selecting the winner's row.
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            row = (
                await session.execute(
                    select(ExtractionTemplate).where(
                        ExtractionTemplate.domain == normalized_domain,
                        ExtractionTemplate.surface == surface,
                        ExtractionTemplate.fingerprint == fingerprint,
                    )
                )
            ).scalar_one()
            row.route_pattern = route_pattern or row.route_pattern
            row.tech_signals = list(tech_signals or row.tech_signals)
            row.last_seen_run_id = run_id or row.last_seen_run_id
            await session.flush()
            return row
    else:
        row.route_pattern = route_pattern or row.route_pattern
        row.tech_signals = list(tech_signals or row.tech_signals)
        row.last_seen_run_id = run_id or row.last_seen_run_id
    await session.flush()
    return row


async def upsert_recipe(
    session: AsyncSession,
    *,
    template: ExtractionTemplate,
    layer: str,
    kind: str,
    payload: dict,
    locale_policy_ref: str | None = None,
    merge_payload: Callable[[dict], dict] | None = None,
) -> tuple[ExtractionRecipe, CompiledExtractionRecipe]:
    def next_payload(existing: dict | None = None) -> dict:
        if merge_payload is None:
            return dict(payload)
        return dict(merge_payload(deepcopy(existing or {})))

    recipe = (
        await session.execute(
            select(ExtractionRecipe)
            .where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == layer,
                ExtractionRecipe.kind == kind,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    created = False
    if recipe is None:
        recipe = ExtractionRecipe(
            template_id=template.id,
            layer=layer,
            kind=kind,
            payload=next_payload(),
            locale_policy_ref=locale_policy_ref,
        )
        try:
            async with session.begin_nested():
                session.add(recipe)
                await session.flush()
            created = True
        except IntegrityError:
            recipe = (
                await session.execute(
                    select(ExtractionRecipe)
                    .where(
                        ExtractionRecipe.template_id == template.id,
                        ExtractionRecipe.layer == layer,
                        ExtractionRecipe.kind == kind,
                    )
                    .with_for_update()
                )
            ).scalar_one()
    if not created:
        merged_payload = next_payload(recipe.payload)
        if (
            recipe.payload != merged_payload
            or recipe.locale_policy_ref != locale_policy_ref
        ):
            recipe.payload = merged_payload
            recipe.locale_policy_ref = locale_policy_ref
            recipe.version += 1
            await session.flush()
    elif recipe.locale_policy_ref != locale_policy_ref:
        recipe.locale_policy_ref = locale_policy_ref
        await session.flush()
    checksum = _checksum(recipe.payload)
    compiled = (
        await session.execute(
            select(CompiledExtractionRecipe).where(
                CompiledExtractionRecipe.recipe_id == recipe.id,
                CompiledExtractionRecipe.checksum == checksum,
            )
        )
    ).scalar_one_or_none()
    if compiled is None:
        compiled = CompiledExtractionRecipe(
            recipe_id=recipe.id,
            compiler_version=EXTRACTION_COMPILER_VERSION,
            checksum=checksum,
            payload=dict(recipe.payload),
        )
        try:
            async with session.begin_nested():
                session.add(compiled)
                await session.flush()
        except IntegrityError:
            compiled = (
                await session.execute(
                    select(CompiledExtractionRecipe).where(
                        CompiledExtractionRecipe.recipe_id == recipe.id,
                        CompiledExtractionRecipe.checksum == checksum,
                    )
                )
            ).scalar_one()
    return recipe, compiled


class LearnOncePersistLockTimeout(RuntimeError):
    """A learned-recipe persist could not acquire its row locks in time.

    Raised (after rolling back the session) when the bounded lock wait in
    :func:`persist_learned_recipe` expires because a peer holds the template or
    recipe row. Callers must treat this as an honest no-learn — the claim
    seam's PROVISIONAL marker ages out via its TTL, so the scope stays
    re-claimable — and never error the crawl.
    """


def _is_lock_timeout_error(exc: DBAPIError) -> bool:
    """True when a DBAPI error is Postgres ``lock_not_available`` (55P03).

    asyncpg's ``LockNotAvailableError`` translates to a generic
    :class:`DBAPIError` (not ``OperationalError``), so matching on the
    SQLSTATE is the only reliable way to recognize an expired
    ``SET LOCAL lock_timeout`` across drivers.
    """

    return getattr(exc.orig, "sqlstate", None) == "55P03" or isinstance(
        exc, OperationalError
    )


async def persist_learned_recipe(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    route_pattern: str,
    fingerprint: str,
    recipe_payload: dict[str, object],
    confidence: float,
    run_id: int | None = None,
    tech_signals: list[str] | None = None,
) -> tuple[ExtractionTemplate, ExtractionRecipe]:
    """Store one learned LEARN-ONCE recipe keyed by (domain, surface, route).

    The executable recipe payload is stored on its own recipe layer/kind so it
    never mingles with selector-rule layers. Confidence lives in the payload so
    version ordering can prefer the most-confident recipe without a new column.

    Raises :class:`LearnOncePersistLockTimeout` when the bounded row-lock wait
    expires (contention with a concurrent writer); the session is rolled back
    before raising so the connection is returned to the pool clean.
    """

    template = await ensure_template(
        session,
        domain=domain,
        surface=surface,
        fingerprint=fingerprint,
        route_pattern=route_pattern,
        tech_signals=tech_signals,
        run_id=run_id,
    )
    payload = dict(recipe_payload)
    payload["_confidence"] = float(confidence)
    payload["_route_pattern"] = route_pattern

    def merge_payload(existing: dict) -> dict:
        # Keep the most-confident recipe; ties keep the newer proposal.
        old_confidence = float(existing.get("_confidence") or 0.0)
        if existing and float(confidence) < old_confidence:
            return existing
        return payload

    # Finding 7: bound every row-lock wait below with the same ``SET LOCAL
    # lock_timeout`` used by ``claim_learn_once_template`` so a persist blocked
    # by a peer fails closed within the configured bound instead of hanging a
    # pooled connection indefinitely.
    try:
        await session.execute(
            text(
                f"SET LOCAL lock_timeout = '{CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS}ms'"
            )
        )
        # Deadlock ordering: every writer for this scope locks template THEN
        # recipe (``claim_learn_once_template`` and
        # ``_locked_active_executable_recipe`` do the same). Without this, a
        # concurrent claimant holding the template row and waiting on the
        # recipe row can deadlock against this transaction holding the recipe
        # row from ``upsert_recipe``'s FOR UPDATE.
        await session.execute(
            select(ExtractionTemplate.id)
            .where(ExtractionTemplate.id == template.id)
            .with_for_update()
        )
        recipe, _compiled = await upsert_recipe(
            session,
            template=template,
            layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
            kind=EXTRACTION_RECIPE_KIND_EXECUTABLE,
            payload=payload,
            merge_payload=merge_payload,
        )
        # Finding 6: the claim seam may have pre-created this row as a
        # PROVISIONAL learn-attempt marker. A grounded compile promotes it to
        # ACTIVE so it enters the release payload (release payloads only
        # surface ACTIVE executables).
        if recipe.status != EXTRACTION_MEMORY_STATUS_ACTIVE:
            recipe.status = EXTRACTION_MEMORY_STATUS_ACTIVE
            await session.flush()
    except DBAPIError as exc:
        if not _is_lock_timeout_error(exc):
            raise
        # Lock wait exceeded ``lock_timeout`` — a peer holds the row. Fail
        # closed: roll back and surface a typed error the caller maps to an
        # honest no-learn.
        await session.rollback()
        raise LearnOncePersistLockTimeout(
            f"persist_learned_recipe lock wait exceeded "
            f"{CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS}ms for {domain}/{surface}"
        ) from exc
    return template, recipe


async def _locked_active_executable_recipe(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    route_pattern: str,
) -> tuple[ExtractionTemplate, ExtractionRecipe] | None:
    """Row-lock the active template + executable recipe for a scope.

    ``SELECT ... FOR UPDATE`` serializes concurrent drift/success updates so the
    consecutive-failure counter can never be lost to a read-modify-write race.
    """

    template = (
        await session.execute(
            select(ExtractionTemplate)
            .where(
                ExtractionTemplate.domain == normalize_domain(domain),
                ExtractionTemplate.surface == surface,
                ExtractionTemplate.route_pattern == route_pattern,
                ExtractionTemplate.status.in_(
                    (
                        EXTRACTION_MEMORY_STATUS_ACTIVE,
                        EXTRACTION_MEMORY_STATUS_TRUSTED,
                    )
                ),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if template is None:
        return None
    recipe = (
        await session.execute(
            select(ExtractionRecipe)
            .where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE,
                ExtractionRecipe.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if recipe is None:
        return None
    return template, recipe


@dataclass(frozen=True, slots=True)
class LearnOnceClaim:
    """A durable, transaction-scoped claim to compile ONE LEARN-ONCE recipe.

    Returned by :func:`claim_learn_once_template` when the caller has won the
    right to run the single model call for a ``(domain, surface, route)`` scope.
    The claim is only valid for as long as the caller's transaction holds the
    ``SELECT ... FOR UPDATE`` lock on ``template``; the model call and the
    subsequent :func:`persist_learned_recipe` must run inside that same
    transaction so the lock serializes concurrent workers.
    """

    template: ExtractionTemplate
    domain: str
    surface: str
    route_pattern: str
    fingerprint: str


def _learn_attempt_is_fresh(payload: dict | None) -> bool:
    """True when a PROVISIONAL learn-attempt marker is still within its TTL.

    A fresh marker means another worker is mid-attempt (or just finished one):
    fail closed. A marker older than ``CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS``
    is treated as abandoned (crashed worker) so a later run can re-attempt —
    an interrupted compile never permanently blocks a template (finding 6).
    """

    marker = (payload or {}).get("_learn_attempt")
    if not isinstance(marker, dict):
        return False
    claimed_at = marker.get("claimed_at")
    if not isinstance(claimed_at, str):
        # Malformed/absent timestamp: treat as fresh so we never race a peer.
        return True
    try:
        claimed = datetime.fromisoformat(claimed_at)
    except ValueError:
        return True
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=UTC)
    age = datetime.now(UTC) - claimed
    return age < timedelta(seconds=CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS)


async def claim_learn_once_template(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    route_pattern: str,
    fingerprint: str,
    run_id: int | None = None,
    tech_signals: list[str] | None = None,
) -> LearnOnceClaim | None:
    """Durably claim the right to compile ONE recipe for a template scope.

    Finding 10: two concurrent URLs/runs can both read "no recipe" from the
    per-run release snapshot and both compile — burning two model calls and
    racing two writes. This turns that best-effort check into a strict,
    transactional guarantee of exactly one compile per new template.

    Finding 6: "exactly one model call" must hold even when the winning worker's
    compile yields NO grounded recipe (no candidate / ungrounded / provider
    error) and therefore persists nothing executable. So the claim writes a
    durable PROVISIONAL learn-attempt marker on the executable-recipe row UNDER
    the template lock and **commits it (releasing the lock) BEFORE the model
    call**. A concurrent worker then blocks on the template insert until that
    commit, re-checks under the lock, sees the fresh marker, and fails closed —
    even though the first worker's compile ultimately wrote no recipe. On a
    successful compile ``persist_learned_recipe`` promotes the same row to
    ACTIVE (release payloads only surface ACTIVE executable recipes, so a bare
    marker never leaks into replay). A marker older than the attempt TTL is an
    abandoned/crashed attempt and is re-claimable so learning never wedges.

    Finding 7 (lock duration): the previous design held the row lock across the
    provider-config lookup AND the LLM call, so a stuck lock could park a pooled
    DB connection for the whole model round-trip. This seam now (a) bounds the
    lock wait with a ``SET LOCAL lock_timeout`` so a worker that cannot acquire
    the lock quickly fails closed instead of hanging a connection, and (b)
    commits the marker before returning so the lock is NOT held across the model
    call at all — the durable marker, not a long-held row lock, enforces
    exactly-once.

    Returns a :class:`LearnOnceClaim` when this worker owns the single compile;
    ``None`` when the scope is already learned or another attempt is in flight
    (honest no-learn — the caller must skip learning and never error the crawl).
    """

    # Ensure the template row exists so there is a row to lock. ``ensure_template``
    # is itself concurrency-safe (unique-index recovery).
    template = await ensure_template(
        session,
        domain=domain,
        surface=surface,
        fingerprint=fingerprint,
        route_pattern=route_pattern,
        tech_signals=tech_signals,
        run_id=run_id,
    )
    # Finding 7: cap how long we wait for the template row lock. A racing worker
    # that cannot acquire it within the bound raises ``lock_not_available``; we
    # fail closed (skip learning) rather than block a pooled connection.
    try:
        await session.execute(
            text(
                f"SET LOCAL lock_timeout = '{CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS}ms'"
            )
        )
        locked = (
            await session.execute(
                select(ExtractionTemplate)
                .where(ExtractionTemplate.id == template.id)
                .with_for_update()
            )
        ).scalar_one()
        # Re-check the executable-recipe row under the lock.
        existing = (
            await session.execute(
                select(ExtractionRecipe)
                .where(
                    ExtractionRecipe.template_id == locked.id,
                    ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                    ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
    except DBAPIError as exc:
        if not _is_lock_timeout_error(exc):
            raise
        # Lock wait exceeded ``lock_timeout`` — a peer holds the row. Fail closed.
        await session.rollback()
        return None

    if existing is not None:
        if existing.status == EXTRACTION_MEMORY_STATUS_ACTIVE:
            # Already learned (this scope has a live recipe): honest no-learn.
            await session.commit()
            return None
        if _learn_attempt_is_fresh(existing.payload):
            # A peer's attempt is in flight (marker within TTL): fail closed.
            await session.commit()
            return None
        # Stale marker from an abandoned attempt: re-claim by refreshing it.
        payload = dict(existing.payload or {})
        payload["_learn_attempt"] = {
            "run_id": run_id,
            "claimed_at": datetime.now(UTC).isoformat(),
        }
        existing.payload = payload
        existing.status = EXTRACTION_MEMORY_STATUS_PROVISIONAL
    else:
        # First claimant for this scope: write the durable PROVISIONAL marker.
        session.add(
            ExtractionRecipe(
                template_id=locked.id,
                layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
                kind=EXTRACTION_RECIPE_KIND_EXECUTABLE,
                payload={
                    "_learn_attempt": {
                        "run_id": run_id,
                        "claimed_at": datetime.now(UTC).isoformat(),
                    }
                },
                status=EXTRACTION_MEMORY_STATUS_PROVISIONAL,
            )
        )
    # Commit the marker so it is durable and the row lock is released BEFORE the
    # model call (findings 6 + 7). A concurrent worker blocked on the template
    # insert now sees the committed marker and fails closed.
    await session.commit()
    return LearnOnceClaim(
        template=locked,
        domain=normalize_domain(domain),
        surface=surface,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
    )


async def _recipe_is_operator_owned(
    session: AsyncSession, *, template_id: uuid.UUID
) -> bool:
    """True when an operator explicitly owns THIS template's recipe.

    Ownership is scoped to the exact ``template_id`` and to explicit ownership /
    override label kinds — a generic domain/surface field-feedback label does not
    exempt a learned recipe from drift self-heal.
    """

    return (
        await session.execute(
            select(func.count())
            .select_from(ExtractionOperatorLabel)
            .where(
                ExtractionOperatorLabel.template_id == template_id,
                ExtractionOperatorLabel.label_kind.in_(
                    EXTRACTION_RECIPE_OWNERSHIP_LABEL_KINDS
                ),
            )
        )
    ).scalar_one() > 0


async def note_recipe_drift_failure(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    route_pattern: str,
    threshold: int,
) -> bool:
    """Count a CONSECUTIVE LEARN-ONCE recipe drift and self-heal when confirmed.

    Mirrors ``crawl/profile/acquisition_contract.note_acquisition_contract_failure``:
    each confirmed recipe-execution drift for a template that owns an executable
    recipe increments a consecutive ``_stale_after_failures`` counter in the
    recipe payload (no new column). A successful replay resets it (see
    ``reset_recipe_drift``). Once the counter reaches ``threshold`` the recipe is
    suspended so future traffic falls through to the floors and can re-learn.

    Concurrency-safe: the template + recipe rows are locked ``FOR UPDATE`` for the
    duration of the read-modify-write. Operator decisions outrank auto-learned
    recipes: an explicit operator ownership label on THIS exact template exempts
    it from auto-suspension.

    Returns ``True`` when the recipe was suspended by this call.
    """

    locked = await _locked_active_executable_recipe(
        session, domain=domain, surface=surface, route_pattern=route_pattern
    )
    if locked is None:
        return False
    template, recipe = locked

    payload = dict(recipe.payload or {})
    stale_value = payload.get("_stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, dict) else {}
    failure_count = int(stale.get("failure_count") or 0) + 1
    should_suspend = failure_count >= max(1, int(threshold or 1))

    if await _recipe_is_operator_owned(session, template_id=template.id):
        should_suspend = False

    payload["_stale_after_failures"] = {
        "failure_count": failure_count,
        "stale": should_suspend,
    }
    recipe.payload = payload
    if should_suspend:
        recipe.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
        template.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
    await session.flush()
    return should_suspend


async def reset_recipe_drift(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    route_pattern: str,
) -> None:
    """Reset the consecutive drift counter after a successful recipe replay.

    Because drift is counted consecutively, any grounded replay clears the
    counter so a recipe that mostly works is never suspended by scattered,
    non-consecutive misses. Concurrency-safe via the same row lock.
    """

    locked = await _locked_active_executable_recipe(
        session, domain=domain, surface=surface, route_pattern=route_pattern
    )
    if locked is None:
        return
    _template, recipe = locked
    payload = dict(recipe.payload or {})
    if not payload.get("_stale_after_failures"):
        return
    payload["_stale_after_failures"] = {"failure_count": 0, "stale": False}
    recipe.payload = payload
    await session.flush()


async def record_extraction_result(
    session: AsyncSession,
    *,
    run_id: int,
    url_result_id: int,
    release_snapshot_id: uuid.UUID | None,
    url: str,
    surface: str,
    result: ExtractionResult,
) -> ExtractionManifest:
    template = await ensure_template(
        session,
        domain=normalize_domain(url),
        surface=surface,
        fingerprint=fingerprint_template(url, surface, result),
        route_pattern=normalize_route(url, surface),
        tech_signals=extract_tech_signals(result),
        run_id=run_id,
    )
    await _record_observed_field_preferences(
        session,
        template=template,
        surface=surface,
        result=result,
    )
    observation = ExtractionObservation(
        template_id=template.id,
        run_id=run_id,
        url_result_id=url_result_id,
        verdict=result.verdict,
        payload={
            "record_count": len(result.records),
            "finding_rule_ids": sorted({row.rule_id for row in result.findings}),
            "contract_outcomes": [
                row.model_dump(mode="json") for row in result.contract_outcomes
            ],
        },
    )
    session.add(observation)
    await record_sentinel_observations(
        session,
        run_id=run_id,
        url_result_id=url_result_id,
        current_domain=template.domain,
        current_surface=template.surface,
        current_route_pattern=template.route_pattern,
        result=result,
    )
    manifest = (
        await session.execute(
            select(ExtractionManifest).where(
                ExtractionManifest.url_result_id == url_result_id
            )
        )
    ).scalar_one_or_none()
    manifest_payload = {
        "fingerprint": template.fingerprint,
        "route_pattern": template.route_pattern,
    }
    if manifest is None:
        manifest = ExtractionManifest(
            run_id=run_id,
            url_result_id=url_result_id,
            release_snapshot_id=release_snapshot_id,
            template_id=template.id,
            manifest_version=EXTRACTION_MANIFEST_VERSION,
            payload=manifest_payload,
        )
        session.add(manifest)
    else:
        manifest.release_snapshot_id = release_snapshot_id
        manifest.template_id = template.id
        manifest.payload = manifest_payload
    await session.flush()
    return manifest


async def _record_observed_field_preferences(
    session: AsyncSession,
    *,
    template: ExtractionTemplate,
    surface: str,
    result: ExtractionResult,
) -> None:
    observed_sources = observed_field_sources(result)
    if not observed_sources:
        return

    def merge_contracts(existing_payload: dict) -> dict:
        return merge_observed_contracts(
            existing_payload,
            template_id=template.id,
            surface=surface,
            observed_sources=observed_sources,
        )

    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": []},
        merge_payload=merge_contracts,
    )


async def purge_extraction_memory(session: AsyncSession) -> dict[str, int]:
    models = (
        ExtractionManifest,
        ExtractionObservation,
        ExtractionReleaseSnapshot,
        CompiledExtractionRecipe,
        ExtractionRecipe,
        ExtractionTemplate,
    )
    counts: dict[str, int] = {}
    for model in models:
        key = f"{model.__tablename__}_deleted"
        counts[key] = int(
            await session.scalar(select(func.count()).select_from(model)) or 0
        )
        await session.execute(delete(model))
    return counts
