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
    create_executable_release_snapshot,
    note_recipe_drift_failure,
    persist_learned_recipe,
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
        )
        return raw

    return client


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

    if not (CASCADE_LEARN_ONCE_TIER_ENABLED and CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL):
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

    url = request.capture.final_url or request.capture.requested_url
    domain = normalize_domain(url)
    route_pattern = normalize_route(url, surface_value)
    recipe_payload = discovery.candidate.recipe.model_dump(mode="json")
    # Stable per (domain, surface, route) so equivalent pages share a template
    # instead of minting a fresh one per crawl (recipe_id carries bundle_id).
    fingerprint = stable_id("learn-once-template", domain, surface_value, route_pattern)
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
    await create_executable_release_snapshot(
        session,
        run_id=None,
        domain=domain,
        surface=surface_value,
    )
    return True


async def note_recipe_drift_after_replay(
    session: AsyncSession,
    *,
    request: ExtractionRequest,
    run_id: int | None,
) -> bool:
    """Record a drift failure for an existing recipe whose replay found nothing.

    Self-heal mirrors ``acquisition_contract``: once drift is confirmed past
    ``CASCADE_RECIPE_STALE_FAILURE_THRESHOLD`` the recipe is suspended and a
    fresh ``release.v2`` snapshot is frozen so future crawls fall through to the
    floors (and can re-learn). Returns ``True`` when the recipe was suspended.
    """

    surface_value = request.surface.value
    url = request.capture.final_url or request.capture.requested_url
    domain = normalize_domain(url)
    route_pattern = normalize_route(url, surface_value)
    suspended = await note_recipe_drift_failure(
        session,
        domain=domain,
        surface=surface_value,
        route_pattern=route_pattern,
        threshold=CASCADE_RECIPE_STALE_FAILURE_THRESHOLD,
    )
    if suspended:
        await create_executable_release_snapshot(
            session,
            run_id=None,
            domain=domain,
            surface=surface_value,
        )
    return suspended
