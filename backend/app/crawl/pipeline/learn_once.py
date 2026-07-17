"""LEARN-ONCE orchestration seam.

The pure, storage-free compiler (``core.extraction_memory.recipe_compiler``)
learns one recipe from the capture bundle; this async layer decides *when* to
invoke it (config + run gates + surface allow-list + new template) and persists
the grounded result as an executable ``release.v2`` recipe. Extraction itself
stays synchronous and side-effect free — nothing here runs inside ``extract()``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.llm.config_service import (
    resolve_provider_api_key,
    resolve_run_config,
)
from app.connectors.llm.errors import ERROR_PREFIX
from app.connectors.llm.provider_client import call_provider_with_retry
from app.core.config.cascade import (
    CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL,
    CASCADE_LEARN_ONCE_PROVIDER_MAX_RETRIES,
    CASCADE_LEARN_ONCE_SURFACES,
    CASCADE_LEARN_ONCE_TIER_ENABLED,
    CASCADE_RECIPE_STALE_FAILURE_THRESHOLD,
)
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.recipe_compiler import compile_recipe
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.extraction.contracts import ExtractionRequest, ExtractionResult
from app.extraction.surfaces import listing_schema, parse_surface, surface_spec
from app.persistence.extraction_memory import (
    LearnOncePersistLockTimeout,
    claim_learn_once_template,
    note_recipe_drift_failure,
    persist_learned_recipe,
    reset_recipe_drift,
)

# LLM task type reused for provider/model + key resolution.
_LEARN_ONCE_TASK_TYPE = "general"
# Confidence assigned to a freshly learned, fully grounded recipe.
_LEARNED_RECIPE_CONFIDENCE = 0.75


def _model_client_for_run(
    session: AsyncSession, *, run_id: int | None
) -> Callable[[str, str], Awaitable[str]]:
    """Build a ``RecipeModelClient`` bound to the run's LLM configuration."""

    async def client(system_prompt: str, user_prompt: str) -> str:
        config = await resolve_run_config(
            session,
            run_id=run_id,
            task_type=_LEARN_ONCE_TASK_TYPE,
            config_snapshot=None,
        )
        if config is None:
            return f"{ERROR_PREFIX} no LLM config available for recipe compilation"
        provider = str(config.get("provider") or "")
        model = str(config.get("model") or "")
        raw, _input_tokens, _output_tokens = await call_provider_with_retry(
            provider=provider,
            model=model,
            api_key=resolve_provider_api_key(
                provider=provider,
                encrypted_value=str(config.get("api_key_encrypted") or ""),
            ),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            # Finding 14: LEARN-ONCE is a single model call, so provider-level
            # retries must be disabled — one grounded attempt, no re-requests.
            max_retries=CASCADE_LEARN_ONCE_PROVIDER_MAX_RETRIES,
        )
        return raw

    return client


def _has_rendered_capture(request: ExtractionRequest) -> bool:
    """True when the capture carries a rendered-DOM artifact the recipe needs.

    Mirrors the availability set consulted by
    ``recipe_executor._check_capture_requirements`` for the ``rendered_dom``
    requirement: an ``artifact_type == "rendered_html"`` artifact must exist.
    """

    return any(
        artifact.artifact_type == "rendered_html"
        for artifact in request.capture.artifacts
    )


def should_attempt_learn_once(
    *,
    surface: str,
    llm_enabled: bool,
    floors_empty: bool,
    is_new_template: bool,
) -> bool:
    """Gate: auto-learn only on the first crawl of a genuinely new template.

    Requires the LEARN-ONCE tier enabled in config, autolearn enabled, the run's
    ``llm_enabled`` setting, an empty deterministic floor for this page, a
    not-yet-learned template, and a surface on the per-surface allow-list.
    """

    if not (
        CASCADE_LEARN_ONCE_TIER_ENABLED and CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL
    ):
        return False
    if not (llm_enabled and floors_empty and is_new_template):
        return False
    return surface in CASCADE_LEARN_ONCE_SURFACES


async def learn_recipe_after_extraction(
    session: AsyncSession,
    *,
    request: ExtractionRequest,
    result: ExtractionResult,
    run_id: int | None,
    llm_enabled: bool,
    is_new_template: bool,
    model_client: Callable[[str, str], Awaitable[str]] | None = None,
) -> bool:
    """Invoke the compiler once and persist a grounded recipe, if gated in.

    Returns ``True`` when a recipe was learned and persisted. Never raises for
    ungrounded/abstained learning — an honest no-recipe simply returns ``False``.
    """

    surface_value = request.surface.value
    floors_empty = not result.records
    if not should_attempt_learn_once(
        surface=surface_value,
        llm_enabled=llm_enabled,
        floors_empty=floors_empty,
        is_new_template=is_new_template,
    ):
        return False

    # Finding 6: the compiled recipe declares ``capture_requirements=("rendered_dom",)``
    # and its replay fails with ``recipe_capture_requirement_missing`` when only an
    # HTTP-only capture exists. Gate the model call on a rendered-DOM artifact so an
    # HTTP-only first pass never burns an LLM request on a recipe that cannot replay.
    if not _has_rendered_capture(request):
        return False

    url = request.capture.final_url or request.capture.requested_url
    domain = normalize_domain(url)
    route_pattern = normalize_route(url, surface_value)
    # Stable per (domain, surface, route) so equivalent pages share a template
    # instead of minting a fresh one per crawl (recipe_id carries bundle_id).
    fingerprint = stable_id("learn-once-template", domain, surface_value, route_pattern)

    # Finding 10: a durable, transactional claim guarantees exactly ONE model
    # call per new template. The snapshot-based ``is_new_template`` check is a
    # per-run read that two concurrent URLs/runs can both pass, so acquire a
    # template-scoped row lock and re-check the executable recipe under it. A
    # losing/blocked worker sees the winner's persisted recipe once it acquires
    # the lock and fails closed (honest no-learn, no model call).
    claim = await claim_learn_once_template(
        session,
        domain=domain,
        surface=surface_value,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        run_id=run_id,
    )
    if claim is None:
        return False

    client = model_client or _model_client_for_run(session, run_id=run_id)
    surface = parse_surface(surface_value)
    discovery = await compile_recipe(
        request,
        surface_spec=surface_spec(surface),
        listing_schema=listing_schema(surface),
        model_client=client,
    )
    if discovery.candidate is None:
        return False

    recipe_payload = discovery.candidate.recipe.model_dump(mode="json")
    # The claim committed (and released its row lock) before the model call —
    # the durable PROVISIONAL marker, not a held lock, enforces exactly-once.
    # ``persist_learned_recipe`` therefore re-acquires the template lock with a
    # bounded wait; on contention it raises instead of blocking indefinitely.
    try:
        await persist_learned_recipe(
            session,
            domain=domain,
            surface=surface_value,
            route_pattern=route_pattern,
            fingerprint=fingerprint,
            recipe_payload=recipe_payload,
            confidence=_LEARNED_RECIPE_CONFIDENCE,
            run_id=run_id,
        )
    except LearnOncePersistLockTimeout:
        # Bounded lock wait expired against a contending writer: honest
        # no-learn (session already rolled back). The claim's PROVISIONAL
        # marker ages out via its TTL, so the scope stays re-claimable.
        return False
    # No detached snapshot: the persisted recipe flows into the next run's
    # unified release payload via ``build_release_payload`` at run creation.
    return True


async def note_recipe_drift_after_replay(
    session: AsyncSession,
    *,
    request: ExtractionRequest,
    run_id: int | None,
) -> bool:
    """Record a drift failure for an existing recipe whose replay found nothing.

    Self-heal mirrors ``acquisition_contract``: once drift is confirmed past
    ``CASCADE_RECIPE_STALE_FAILURE_THRESHOLD`` the recipe (and its template) are
    suspended so future crawls fall through to the floors (and can re-learn).
    The suspended status is picked up by the next run's unified release payload.
    Returns ``True`` when the recipe was suspended.
    """

    surface_value = request.surface.value
    url = request.capture.final_url or request.capture.requested_url
    domain = normalize_domain(url)
    route_pattern = normalize_route(url, surface_value)
    return await note_recipe_drift_failure(
        session,
        domain=domain,
        surface=surface_value,
        route_pattern=route_pattern,
        threshold=CASCADE_RECIPE_STALE_FAILURE_THRESHOLD,
    )


async def reset_recipe_drift_after_successful_replay(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
    result: ExtractionResult,
) -> None:
    """Reset the consecutive drift counter after a grounded recipe replay.

    Finding 12: drift is counted consecutively and only a successful replay
    should clear it, so a recipe that mostly works is never suspended by
    scattered, non-consecutive misses. Only a real recipe-tier replay WITH
    records qualifies; other tiers (deterministic/ml/llm) leave the counter
    untouched. Keyed by the same ``(domain, surface, route)`` used by drift and
    persistence so the reset targets exactly the replayed recipe.
    """

    if result.diagnostics.extractor_tier != "recipe" or not result.records:
        return
    surface_value = surface or result.surface.value
    domain = normalize_domain(url)
    route_pattern = normalize_route(url, surface_value)
    await reset_recipe_drift(
        session,
        domain=domain,
        surface=surface_value,
        route_pattern=route_pattern,
    )
