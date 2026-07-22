from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import uuid
from typing import TYPE_CHECKING, Any, cast

from cachetools import LRUCache
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS,
    EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
    EXTRACTION_CONTRACT_RESOLVER_OBSERVED,
    EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_MEMORY_STATUS_TRUSTED,
    EXTRACTION_MEMORY_STATUS_PROVISIONAL,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_EXECUTABLE,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    EXTRACTION_RECIPE_LAYER_ORDER,
    EXTRACTION_RECIPE_OWNERSHIP_LABEL_KINDS,
    EXTRACTION_RELEASE_VERSION,
    SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD,
    SENTINEL_OBSERVATION_KIND,
    SENTINEL_SUSPENSION_KIND,
)
from app.core.domain_utils import normalize_domain
from app.core.config.cascade import (
    CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS,
    CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS,
)
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_source_pattern,
    normalize_route,
    source_pattern,
)
from app.models.crawl_run import CrawlRun
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
    merge_observed_sources as _merge_observed_sources,
)

if TYPE_CHECKING:
    from app.extraction.contracts import ExtractionResult


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class RecipeCompileError(ValueError):
    """Recipe layers cannot be merged into one bounded runtime recipe."""


def compile_recipe_layers(recipes: list[ExtractionRecipe]) -> dict[str, object]:
    """Flatten scoped recipe layers into one bounded payload.

    Higher layers may override lower layers. Two recipes at the same layer/kind
    that define different rules for the same field are ambiguous and fail
    closed.
    """

    ordered = sorted(
        recipes,
        key=lambda row: (
            _layer_rank(row.layer),
            row.kind,
            row.version,
            str(row.id),
        ),
    )
    selectors: dict[str, dict[str, object]] = {}
    contracts: dict[str, dict[str, object]] = {}
    provenance: list[dict[str, object]] = []
    layer_signatures: dict[tuple[str, str, str], str] = {}
    for recipe in ordered:
        payload = dict(recipe.payload or {})
        provenance.append(
            {
                "recipe_id": str(recipe.id),
                "layer": recipe.layer,
                "kind": recipe.kind,
                "version": recipe.version,
            }
        )
        if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS:
            for row in list(payload.get("rules") or []):
                if not isinstance(row, dict):
                    continue
                field = str(row.get("field_name") or row.get("canonical_field") or "")
                selector = str(row.get("css_selector") or "")
                _merge_layer_rule(
                    selectors,
                    layer_signatures,
                    recipe=recipe,
                    field=field,
                    value=selector,
                    payload=dict(row),
                )
        elif recipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS:
            for row in list(payload.get("contracts") or []):
                if not isinstance(row, dict):
                    continue
                field = str(row.get("canonical_field") or row.get("field_name") or "")
                selected = str(row.get("selected_source") or "")
                _merge_layer_rule(
                    contracts,
                    layer_signatures,
                    recipe=recipe,
                    field=field,
                    value=selected,
                    payload=dict(row),
                )
    return {
        "compiler_version": EXTRACTION_COMPILER_VERSION,
        "selector_rules": list(selectors.values()),
        "contracts": list(contracts.values()),
        "provenance": provenance,
    }


def _merge_layer_rule(
    target: dict[str, dict[str, object]],
    layer_signatures: dict[tuple[str, str, str], str],
    *,
    recipe: ExtractionRecipe,
    field: str,
    value: str,
    payload: dict[str, object],
) -> None:
    field_key = field.strip().lower()
    value_key = value.strip()
    if not field_key or not value_key:
        return
    layer_key = (recipe.layer, recipe.kind, field_key)
    existing = layer_signatures.get(layer_key)
    if existing is not None and existing != value_key:
        raise RecipeCompileError(
            f"ambiguous {recipe.kind} override for {field_key} at {recipe.layer}"
        )
    layer_signatures[layer_key] = value_key
    target[field_key] = dict(payload)


def _layer_rank(layer: str) -> int:
    try:
        return EXTRACTION_RECIPE_LAYER_ORDER.index(layer)
    except ValueError:
        return len(EXTRACTION_RECIPE_LAYER_ORDER)


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


async def build_release_payload(
    session: AsyncSession, *, domain: str, surface: str
) -> dict[str, object]:
    templates = list(
        (
            await session.execute(
                select(ExtractionTemplate).where(
                    ExtractionTemplate.domain == str(domain or "").strip().lower(),
                    ExtractionTemplate.surface.in_((surface, DEFAULT_FALLBACK_SURFACE)),
                    ExtractionTemplate.status.in_(
                        (
                            EXTRACTION_MEMORY_STATUS_ACTIVE,
                            EXTRACTION_MEMORY_STATUS_TRUSTED,
                        )
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    template_rows: list[dict[str, object]] = []
    for template in templates:
        recipes = list(
            (
                await session.execute(
                    select(ExtractionRecipe).where(
                        ExtractionRecipe.template_id == template.id,
                        ExtractionRecipe.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        compiled_recipe = compile_recipe_layers(recipes)
        contracts = list(cast(list[dict], compiled_recipe["contracts"]))
        selector_rules = list(cast(list[dict], compiled_recipe["selector_rules"]))
        row: dict[str, object] = {
            "template_id": str(template.id),
            "fingerprint": template.fingerprint,
            "surface": template.surface,
            "route_pattern": template.route_pattern,
            "status": template.status,
            "contracts": contracts,
            "selector_rules": selector_rules,
            "compiled_recipe": compiled_recipe,
        }
        executable = _executable_recipe_block(recipes)
        if executable is not None:
            row["executable_recipe"] = executable["recipe"]
            row["confidence"] = executable["confidence"]
        template_rows.append(row)
    return {
        "schema_version": EXTRACTION_RELEASE_VERSION,
        "domain": domain,
        "surface": surface,
        "templates": template_rows,
    }


def _executable_recipe_block(
    recipes: list[ExtractionRecipe],
) -> dict[str, object] | None:
    """Pick the most-confident active executable recipe for one template.

    Executable recipes live on their own recipe layer/kind; the caller embeds the
    winner under ``executable_recipe`` so recipe replay never mixes with the
    selector/contract ``compiled_recipe`` block. Confidence lives in the payload
    (``_confidence``); ties keep the higher recipe version.
    """

    executable = [
        recipe
        for recipe in recipes
        if recipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE
        and isinstance(recipe.payload, dict)
    ]
    if not executable:
        return None
    winner = max(
        executable,
        key=lambda recipe: (
            float(dict(recipe.payload).get("_confidence") or 0.0),
            recipe.version,
        ),
    )
    compiled = {
        key: value
        for key, value in dict(winner.payload).items()
        if not str(key).startswith("_")
    }
    return {
        "recipe": compiled,
        "confidence": float(dict(winner.payload).get("_confidence") or 0.0),
    }


def selector_rules_from_release(
    payload: dict[str, object], *, surface: str
) -> list[dict[str, object]]:
    raw_templates = payload.get("templates")
    templates = list(raw_templates) if isinstance(raw_templates, list) else []
    ordered_surfaces = (surface, DEFAULT_FALLBACK_SURFACE)
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for candidate_surface in ordered_surfaces:
        for template in templates:
            if not isinstance(template, dict):
                continue
            if str(template.get("surface") or "") != candidate_surface:
                continue
            if str(
                template.get("status") or ""
            ).strip().lower() == EXTRACTION_MEMORY_STATUS_SUSPENDED or bool(
                template.get("sentinel_suspended")
            ):
                continue
            for row in list(template.get("selector_rules") or []):
                if not isinstance(row, dict):
                    continue
                signature = (
                    str(row.get("field_name") or "").strip().lower(),
                    str(row.get("css_selector") or "").strip(),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                rules.append(dict(row))
    return rules


async def create_release_snapshot(
    session: AsyncSession, *, run_id: int, domain: str, surface: str
) -> ExtractionReleaseSnapshot:
    row = ExtractionReleaseSnapshot(
        run_id=run_id,
        domain=domain,
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION,
        payload=await build_release_payload(session, domain=domain, surface=surface),
    )
    session.add(row)
    await session.flush()
    return row


async def create_candidate_release_snapshot(
    session: AsyncSession, *, domain: str, surface: str
) -> ExtractionReleaseSnapshot:
    """Create an immutable candidate release without making it active for a run."""

    row = ExtractionReleaseSnapshot(
        run_id=None,
        domain=domain,
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION,
        payload=await build_release_payload(session, domain=domain, surface=surface),
    )
    session.add(row)
    await session.flush()
    return row


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


async def active_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int
) -> ExtractionReleaseSnapshot | None:
    return (
        await session.execute(
            select(ExtractionReleaseSnapshot).where(
                ExtractionReleaseSnapshot.run_id == run_id
            )
        )
    ).scalar_one_or_none()


async def activate_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int, release_snapshot_id: uuid.UUID
) -> ExtractionReleaseSnapshot:
    """Atomically point a run at an existing immutable release snapshot."""

    run = (
        await session.execute(
            select(CrawlRun).where(CrawlRun.id == run_id).with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError(f"unknown crawl run: {run_id}")
    target = (
        await session.execute(
            select(ExtractionReleaseSnapshot)
            .where(ExtractionReleaseSnapshot.id == release_snapshot_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise ValueError(f"unknown release snapshot: {release_snapshot_id}")
    if target.run_id not in {None, run_id}:
        raise ValueError("release snapshot is already active for another run")
    if target.domain != normalize_domain(run.url) or target.surface != run.surface:
        raise ValueError("release snapshot is incompatible with crawl run")
    current = await active_release_snapshot_for_run(session, run_id=run_id)
    if current is not None and current.id != target.id:
        current.run_id = None
        await session.flush()
    target.run_id = run_id
    run.extraction_release_snapshot_id = target.id
    await session.flush()
    return target


async def rollback_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int, target_release_snapshot_id: uuid.UUID
) -> ExtractionReleaseSnapshot:
    """Rollback by re-pointing the run; release payload history stays immutable."""

    return await activate_release_snapshot_for_run(
        session,
        run_id=run_id,
        release_snapshot_id=target_release_snapshot_id,
    )


# Per-URL DB budget: every URL in a run used to reload the run's frozen release
# payload 2-4x (selector rules + runtime snapshot + retries), each time through
# a fresh per-URL session that could not share the identity map. A persisted
# release snapshot is immutable (INVARIANTS §17) and keyed by an app-generated
# UUID, so the payload is memoized at process level keyed by snapshot id. The
# bound keeps a long-lived worker from accumulating payloads across runs; only
# a handful of runs are in flight per process at once.
_RELEASE_PAYLOAD_CACHE_MAX_ENTRIES = 8
_release_payload_cache: LRUCache[uuid.UUID, dict[str, object]] = LRUCache(
    maxsize=_RELEASE_PAYLOAD_CACHE_MAX_ENTRIES
)


def reset_release_payload_cache() -> None:
    """Drop memoized release payloads (test isolation / post-migration reloads)."""

    _release_payload_cache.clear()


async def load_release_payload(
    session: AsyncSession, release_snapshot_id: uuid.UUID | None
) -> dict[str, object]:
    if release_snapshot_id is None:
        return {}
    cached = _release_payload_cache.get(release_snapshot_id)
    if cached is not None:
        # Hand out a copy: callers keep the historical per-call mutable-copy
        # semantics (``_load_runtime_snapshot`` annotates the returned dict).
        return deepcopy(cached)
    row = await session.get(ExtractionReleaseSnapshot, release_snapshot_id)
    if row is None:
        # Never memoize a miss: the row may be created later in this process.
        return {}
    # CRITICAL 2: a persisted release snapshot is frozen. Return the stored
    # payload unchanged so in-flight runs keep replaying the exact recipes they
    # were created with. Current template/recipe suspension status is applied
    # only while BUILDING a future snapshot (see ``build_release_payload``,
    # which filters to active/trusted templates and active recipes).
    payload = deepcopy(row.payload)
    _release_payload_cache[release_snapshot_id] = deepcopy(payload)
    return payload


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
    await _record_sentinel_observations(
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
    if (
        result.verdict not in EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS
        or not result.records
    ):
        return
    evidence_by_id = {row.evidence_id: row for row in result.evidence}
    winner_ids = {
        row.accepted_evidence_ids[0]
        for row in result.decisions
        if row.status == "resolved" and row.accepted_evidence_ids
    }
    observed_sources: dict[str, list[str]] = {}
    for state in result.field_states:
        if state.state not in {"captured_published", "captured_and_resolved"}:
            continue
        if state.field.startswith("variants."):
            continue
        winner_id = next(
            (
                evidence_id
                for evidence_id in state.evidence_ids
                if evidence_id in winner_ids
            ),
            next(iter(state.evidence_ids), None),
        )
        evidence = evidence_by_id.get(winner_id) if winner_id else None
        if evidence is None:
            continue
        source = normalize_source_pattern(
            source_pattern(evidence.collector_id, evidence.locator.value)
        )
        if source:
            observed_sources[evidence.fact_type] = [source]
    if not observed_sources:
        return

    def merge_contracts(existing_payload: dict) -> dict:
        contracts = [
            dict(row)
            for row in existing_payload.get("contracts", [])
            if isinstance(row, dict)
        ]
        contracts_by_field = {
            str(row.get("canonical_field") or ""): row for row in contracts
        }
        for canonical_field, sources in observed_sources.items():
            contract = contracts_by_field.get(canonical_field)
            if contract is None:
                selected_source = sources[0]
                contract = {
                    "id": str(uuid.uuid4()),
                    "template_id": str(template.id),
                    "surface": surface,
                    "canonical_field": canonical_field,
                    "candidates": [],
                    "latest_values": [],
                    "success_count": 0,
                    "rejection_count": 0,
                    "resolver_rule": EXTRACTION_CONTRACT_RESOLVER_OBSERVED,
                    "selected_source": selected_source,
                    "selection_origin": EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC,
                    "selection_history": [
                        {
                            "selected_source": selected_source,
                            "source": EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
                        }
                    ],
                    "status": EXTRACTION_MEMORY_STATUS_ACTIVE,
                }
                contracts.append(contract)
                contracts_by_field[canonical_field] = contract
            _merge_observed_sources(contract, sources)
        return {"contracts": contracts}

    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": []},
        merge_payload=merge_contracts,
    )


async def _record_sentinel_observations(
    session: AsyncSession,
    *,
    run_id: int,
    url_result_id: int,
    current_domain: str,
    current_surface: str,
    current_route_pattern: str,
    result: ExtractionResult,
) -> None:
    for observation in result.sentinel_observations:
        claimed_template_id = _uuid_or_none(observation.template_id)
        template_id = await _sentinel_template_in_scope(
            session,
            template_id=claimed_template_id,
            domain=current_domain,
            surface=current_surface,
            route_pattern=current_route_pattern,
        )
        session.add(
            ExtractionObservation(
                template_id=template_id,
                run_id=run_id,
                url_result_id=url_result_id,
                verdict=observation.state,
                payload={
                    "kind": SENTINEL_OBSERVATION_KIND,
                    **observation.model_dump(mode="json"),
                },
            )
        )
        if observation.state == "critical_drift" and template_id is not None:
            await _suspend_confirmed_critical_drift_template(
                session,
                template_id=template_id,
                run_id=run_id,
                url_result_id=url_result_id,
            )


async def _sentinel_template_in_scope(
    session: AsyncSession,
    *,
    template_id: uuid.UUID | None,
    domain: str,
    surface: str,
    route_pattern: str,
) -> uuid.UUID | None:
    if template_id is None:
        return None
    return (
        await session.execute(
            select(ExtractionTemplate.id).where(
                ExtractionTemplate.id == template_id,
                ExtractionTemplate.domain == domain,
                ExtractionTemplate.surface == surface,
                ExtractionTemplate.route_pattern == route_pattern,
            )
        )
    ).scalar_one_or_none()


async def _suspend_confirmed_critical_drift_template(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    run_id: int,
    url_result_id: int,
) -> None:
    with session.no_autoflush:
        template = (
            await session.execute(
                select(ExtractionTemplate)
                .where(ExtractionTemplate.id == template_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if template is None or template.status == EXTRACTION_MEMORY_STATUS_SUSPENDED:
        return
    await session.flush()
    confirmed_count = (
        await session.execute(
            select(func.count())
            .select_from(ExtractionObservation)
            .where(
                ExtractionObservation.template_id == template_id,
                ExtractionObservation.verdict == "critical_drift",
                ExtractionObservation.payload["kind"].as_string()
                == SENTINEL_OBSERVATION_KIND,
            )
        )
    ).scalar_one()
    if confirmed_count < SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD:
        return
    template.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
    session.add(
        ExtractionObservation(
            template_id=template_id,
            run_id=run_id,
            url_result_id=url_result_id,
            verdict=EXTRACTION_MEMORY_STATUS_SUSPENDED,
            payload={
                "kind": SENTINEL_SUSPENSION_KIND,
                "template_id": str(template_id),
                "confirmed_critical_drift_count": confirmed_count,
                "next_action": "route_future_traffic_to_generic_until_recipe_is_restored",
            },
        )
    )


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


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


# ---------------------------------------------------------------------------
# Knowledge compatibility projections.
#
# Query/projection owners for the thin HTTP handlers in ``api/knowledge.py``.
# Response shapes are the historical compatibility shapes; handlers only add
# HTTP concerns (auth, status codes).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KnowledgeSiteProjection:
    """Per-domain extraction-memory site row for ``GET /api/knowledge/sites``."""

    id: uuid.UUID
    domain: str
    current_version: int
    projection_status: str
    last_projected_run_id: int | None
    last_projected_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeContractLocation:
    """A stored contract payload plus the template row that owns it."""

    template: ExtractionTemplate
    contract: dict[str, Any]


async def list_knowledge_site_projections(
    session: AsyncSession,
) -> list[KnowledgeSiteProjection]:
    """Project all templates into one row per domain, ordered by domain."""

    templates = list(
        (await session.execute(select(ExtractionTemplate))).scalars().all()
    )
    version_rows = (
        await session.execute(
            select(
                ExtractionRecipe.template_id,
                func.max(ExtractionRecipe.version),
            ).group_by(ExtractionRecipe.template_id)
        )
    ).all()
    latest_version_by_template = {
        template_id: int(version)
        for template_id, version in version_rows
        if version is not None
    }
    domains: dict[str, list[ExtractionTemplate]] = {}
    for template in templates:
        domains.setdefault(template.domain, []).append(template)
    return [
        KnowledgeSiteProjection(
            id=rows[0].id,
            domain=domain,
            current_version=max(
                (latest_version_by_template.get(row.id, 1) for row in rows),
                default=1,
            ),
            projection_status="active",
            last_projected_run_id=max(
                (row.last_seen_run_id or 0 for row in rows), default=0
            )
            or None,
            last_projected_at=max((row.updated_at for row in rows), default=None),
        )
        for domain, rows in sorted(domains.items())
    ]


async def list_template_contracts(
    session: AsyncSession, template: ExtractionTemplate
) -> list[dict[str, Any]]:
    recipe = await _contract_recipe(session, template.id)
    return [
        dict(row) for row in (recipe.payload.get("contracts", []) if recipe else [])
    ]


async def list_domain_contracts(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
) -> list[dict[str, Any]]:
    """All stored contract rows for the filtered templates, operator first."""

    query = select(ExtractionTemplate)
    if domain:
        query = query.where(ExtractionTemplate.domain == normalize_domain(domain))
    if surface:
        query = query.where(ExtractionTemplate.surface == surface)
    templates = list((await session.execute(query)).scalars().all())
    contracts: list[dict[str, Any]] = []
    for template in templates:
        contracts.extend(await list_template_contracts(session, template))
    contracts.sort(
        key=lambda row: (
            row.get("selection_origin") != "operator",
            row.get("canonical_field", ""),
        )
    )
    return contracts


async def find_contract_location(
    session: AsyncSession, contract_id: str
) -> KnowledgeContractLocation | None:
    for template in list(
        (await session.execute(select(ExtractionTemplate))).scalars().all()
    ):
        for contract in await list_template_contracts(session, template):
            if str(contract.get("id")) == contract_id:
                return KnowledgeContractLocation(template=template, contract=contract)
    return None


def select_contract_source(
    contract: dict[str, Any], *, selected_source: str
) -> dict[str, Any]:
    """Record an operator source selection on a stored contract payload."""

    contract["selected_source"] = selected_source
    contract["selection_origin"] = "operator"
    history = list(contract.get("selection_history") or [])
    history.append({"selected_source": selected_source, "scope": "template"})
    contract["selection_history"] = history
    return contract


async def store_template_contract(
    session: AsyncSession, template: ExtractionTemplate, contract: dict[str, Any]
) -> None:
    contracts = await list_template_contracts(session, template)
    contracts = [
        row for row in contracts if str(row.get("id")) != str(contract.get("id"))
    ]
    contracts.append(contract)
    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": contracts},
    )


async def _contract_recipe(
    session: AsyncSession, template_id: uuid.UUID
) -> ExtractionRecipe | None:
    return (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template_id,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS,
            )
        )
    ).scalar_one_or_none()
