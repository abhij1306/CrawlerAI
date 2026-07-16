"""Background execution of an AI-visibility run.

Entry point ``run_benchmark(run_id)`` is scheduled via FastAPI ``BackgroundTasks``
(the product-intelligence pattern). It opens its own ``SessionLocal`` and:

  1. loads pending executions in randomized order,
  2. runs them through a small ``asyncio.Semaphore`` (provider is rate-limited),
  3. per execution: call adapter -> parse -> (optionally resolve redirects) ->
     score -> persist immediately, so partial progress survives a crash,
  4. finalizes the run status and computed summary.

Each request is fully independent: ``store=false``, no ``previous_interaction_id``,
and the tracked brand/competitor list is NEVER sent to the provider.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.ai_visibility.contracts import AnswerEngineRequest, AnswerEngineResponse
from app.ai_visibility.gemini import (
    AiVisibilityProviderError,
    GeminiAnswerEngineAdapter,
    is_retryable,
    resolve_redirect,
)
from app.ai_visibility.anthropic import AnthropicAnswerEngineAdapter
from app.ai_visibility.openrouter import OpenRouterAnswerEngineAdapter
from app.ai_visibility.scoring import ScoringConfig, aggregate_run, score_execution
from app.core.config.ai_visibility import (
    AI_VISIBILITY_ERROR_PARSE,
    AI_VISIBILITY_EXECUTION_STATUS_COMPLETED,
    AI_VISIBILITY_EXECUTION_STATUS_FAILED,
    AI_VISIBILITY_EXECUTION_STATUS_PENDING,
    AI_VISIBILITY_EXECUTION_STATUS_RUNNING,
    AI_VISIBILITY_RUN_STATUS_COMPLETED,
    AI_VISIBILITY_RUN_STATUS_DEGRADED,
    AI_VISIBILITY_RUN_STATUS_FAILED,
    AI_VISIBILITY_RUN_STATUS_CANCELLED,
    AI_VISIBILITY_RUN_STATUS_RUNNING,
    AI_VISIBILITY_ERROR_RUN_DEADLINE,
    AI_VISIBILITY_ERROR_TIMEOUT,
    AI_VISIBILITY_PROVIDER_ANTHROPIC,
    AI_VISIBILITY_PROVIDER_GEMINI,
    ai_visibility_settings,
)
from app.core.database import SessionLocal
from app.models.ai_visibility import AiVisibilityExecution, AiVisibilityRun

logger = logging.getLogger(__name__)

_provider_pacing_locks: dict[str, asyncio.Lock] = {}
_provider_last_request_started: dict[str, float] = {}


def _minimum_request_interval(provider: str) -> float:
    if provider == AI_VISIBILITY_PROVIDER_GEMINI:
        return max(0.0, ai_visibility_settings.gemini_min_request_interval_seconds)
    return max(0.0, ai_visibility_settings.openrouter_min_request_interval_seconds)


async def pace_provider_request(provider: str) -> None:
    """Space provider request starts across concurrent runs in this process."""
    lock = _provider_pacing_locks.setdefault(provider, asyncio.Lock())
    async with lock:
        interval = _minimum_request_interval(provider)
        last_started = _provider_last_request_started.get(provider)
        if last_started is not None and interval > 0:
            remaining = interval - (time.monotonic() - last_started)
            if remaining > 0:
                await asyncio.sleep(remaining)
        _provider_last_request_started[provider] = time.monotonic()


def _retry_delay(attempt: int, error: AiVisibilityProviderError) -> float:
    """Seconds to wait before the next attempt.

    Prefers the provider-advised ``Retry-After`` (clamped to the configured max);
    otherwise exponential backoff ``base * 2**attempt`` capped at the max, plus a
    small deterministic jitter so serial retries don't align to the exact
    quota-reset boundary. Jitter is derived from ``attempt`` (not RNG) to stay
    reproducible.
    """
    cap = ai_visibility_settings.retry_max_delay_seconds
    if error.retry_after_seconds is not None:
        return min(error.retry_after_seconds, cap)
    base = ai_visibility_settings.retry_base_delay_seconds * (2**attempt)
    jitter_span = ai_visibility_settings.retry_jitter_seconds
    # Deterministic fractional jitter in [0, jitter_span): spreads retries a bit
    # without needing Math.random/RNG (which is unavailable/undesirable here).
    jitter = (attempt * 0.37) % 1.0 * jitter_span
    return min(base, cap) + jitter


def _citation_payload(citation) -> dict:
    return {
        "ordinal": citation.ordinal,
        "redirect_url": citation.url,
        "resolved_url": None,
        "domain": citation.domain,
        "title": citation.title,
        "start_index": citation.start_index,
        "end_index": citation.end_index,
        "cited_text": citation.cited_text,
    }


def _dedup_citations(citations: list[dict]) -> list[dict]:
    """Collapse citations that point at the same source URL.

    Grounded providers (Anthropic, Gemini, OpenRouter) emit one citation per
    supported *text span*, so a source cited in three sentences appears three
    times. The UI and ``citation_count`` want one row per distinct source. Keeps
    the first occurrence (its ``cited_text``) and re-numbers ``ordinal`` densely.
    URL is the identity; a citation with no URL falls back to (domain, title) so
    it is not silently dropped.
    """
    seen: set = set()
    deduped: list[dict] = []
    for citation in citations:
        url = str(citation.get("redirect_url") or "").strip()
        key = url or (citation.get("domain"), citation.get("title"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({**citation, "ordinal": len(deduped)})
    return deduped


def _snapshot_provider_surface(provider_id: str) -> tuple[list[str], bool | None, str]:
    """The grounding tool + storage posture recorded in ``request_snapshot``.

    Each provider is stateless per request, but expresses it differently: Gemini
    sends ``store=false``; Anthropic and the OpenRouter chat surface have no
    equivalent request flag, so ``store`` is ``None`` and the control is noted.
    """
    if provider_id == AI_VISIBILITY_PROVIDER_GEMINI:
        return ["google_search"], False, "store_false"
    if provider_id == AI_VISIBILITY_PROVIDER_ANTHROPIC:
        return (
            ["anthropic:web_search"],
            None,
            "not_exposed_by_messages_surface",
        )
    return (
        ["openrouter:web_search(engine=native)"],
        None,
        "not_exposed_by_chat_completions_surface",
    )


async def _call_with_retries(
    adapter, request: AnswerEngineRequest
) -> tuple[AnswerEngineResponse | None, AiVisibilityProviderError | None]:
    """Call the provider with pacing, a hard per-call ceiling, and retries.

    Returns ``(response, None)`` on success or ``(None, last_error)`` once the
    attempt budget is spent. A single call can never run past
    ``max_call_seconds`` (``asyncio.wait_for`` guards the HTTP client), and the
    whole loop is bounded by ``max_retries``.
    """
    attempts = ai_visibility_settings.max_retries + 1
    last_error: AiVisibilityProviderError | None = None
    for attempt in range(attempts):
        try:
            await pace_provider_request(adapter.provider_id)
            # Hard per-call ceiling independent of the HTTP client timeout: a
            # stalled call (hung socket, redirect loop) can never run past this.
            response = await asyncio.wait_for(
                adapter.execute(request),
                timeout=ai_visibility_settings.max_call_seconds,
            )
            return response, None
        except TimeoutError:
            last_error = AiVisibilityProviderError(
                "provider call exceeded max_call_seconds "
                f"({ai_visibility_settings.max_call_seconds}s)",
                error_code=AI_VISIBILITY_ERROR_TIMEOUT,
                retryable=True,
            )
        except AiVisibilityProviderError as exc:
            last_error = exc
            if not (exc.retryable and is_retryable(exc.error_code)):
                break
        if attempt == attempts - 1:
            break
        await asyncio.sleep(_retry_delay(attempt, last_error))
    return None, last_error


async def _run_single(
    *,
    adapter,
    execution: AiVisibilityExecution,
    system_instruction: str,
    model: str,
    scoring_config: ScoringConfig,
) -> None:
    request = AnswerEngineRequest(
        prompt=execution.prompt_text_snapshot,
        system_instruction=system_instruction,
        model=model,
        timeout_seconds=ai_visibility_settings.request_timeout_seconds,
    )
    tools, store, storage_control = _snapshot_provider_surface(adapter.provider_id)
    # Snapshot exactly what determines the request. Proves statelessness and that
    # no brand list is transmitted. Never store the API key.
    execution.request_snapshot = {
        "provider": adapter.provider_id,
        "model": request.model,
        "input": request.prompt,
        "visible_prompt": execution.prompt_text_snapshot,
        "effective_prompt": request.prompt,
        "system_instruction": request.system_instruction,
        "tools": tools,
        "store": store,
        "provider_storage_control": storage_control,
        "stateless": True,
        "benchmark_mode": scoring_config.benchmark_mode,
        "country_code": scoring_config.country_code,
        "language_code": scoring_config.language_code,
    }

    response, last_error = await _call_with_retries(adapter, request)

    if response is None:
        execution.status = AI_VISIBILITY_EXECUTION_STATUS_FAILED
        execution.error_code = (
            last_error.error_code if last_error else AI_VISIBILITY_ERROR_PARSE
        )
        execution.error_message = str(last_error) if last_error else "unknown error"
        execution.completed_at = datetime.now(UTC)
        return

    # One row per distinct source URL. Providers cite the same source once per
    # supported text span, which otherwise inflates the list and citation_count.
    citations = _dedup_citations([_citation_payload(c) for c in response.citations])

    # Optional, best-effort resolution of redirect URLs to the real cited page.
    # Resolution failures fall back to direct URL/title evidence.
    if ai_visibility_settings.resolve_citation_urls and citations:
        resolved = await asyncio.gather(
            *(resolve_redirect(c["redirect_url"]) for c in citations),
            return_exceptions=True,
        )
        for citation, final_url in zip(citations, resolved):
            if isinstance(final_url, str):
                citation["resolved_url"] = final_url

    search_events = [
        {
            "sequence": event.sequence,
            "query": event.query,
            "call_id": event.call_id,
            "call_sequence": event.call_sequence,
            "query_sequence": event.query_sequence,
        }
        for event in response.search_events
    ]

    score = score_execution(
        answer_text=response.answer_text,
        search_events=search_events,
        citations=citations,
        search_used=response.search_used,
        config=scoring_config,
        prompt_text=execution.prompt_text_snapshot,
        query_text_available=bool(
            response.provider_metadata.get("query_text_available", True)
        ),
    )
    # Attach per-citation classification back onto stored citations.
    from app.ai_visibility.scoring import classify_citation

    execution.citations = [classify_citation(c, scoring_config) for c in citations]
    execution.answer_text = response.answer_text
    execution.search_used = response.search_used
    execution.search_events = search_events
    execution.score = score
    execution.provider_metadata = response.provider_metadata
    execution.latency_ms = response.latency_ms
    execution.status = AI_VISIBILITY_EXECUTION_STATUS_COMPLETED
    execution.error_code = ""
    execution.error_message = ""
    execution.completed_at = datetime.now(UTC)


async def _execute_one(
    *,
    execution_id: int,
    adapter,
    system_instruction: str,
    model: str,
    scoring_config: ScoringConfig,
    semaphore: asyncio.Semaphore,
    deadline: float,
) -> None:
    """Run a single execution inside its OWN session.

    Each concurrent worker owns a private ``AsyncSession``. SQLAlchemy async
    sessions are not safe for concurrent use, so sharing one across the
    ``asyncio.gather`` fan-out corrupts session state (``IllegalStateChangeError``
    on overlapping commits). A session per task keeps commits isolated.
    """
    async with semaphore, SessionLocal() as session:
        execution = await session.get(AiVisibilityExecution, execution_id)
        if execution is None:
            return
        # Cooperative cancel: if the run was killed since the fan-out started,
        # stop at this execution boundary instead of hitting the provider again.
        run = await session.get(AiVisibilityRun, execution.run_id)
        if run is not None and run.status == AI_VISIBILITY_RUN_STATUS_CANCELLED:
            return
        # Per-run wall-clock cutoff: once the run's deadline has passed, stop at
        # this boundary and terminalize instead of starting another provider call.
        # Bounds total run duration even if every remaining call is slow/throttled.
        if time.monotonic() >= deadline:
            execution.status = AI_VISIBILITY_EXECUTION_STATUS_FAILED
            execution.error_code = AI_VISIBILITY_ERROR_RUN_DEADLINE
            execution.error_message = (
                "run exceeded max_run_seconds "
                f"({ai_visibility_settings.max_run_seconds}s)"
            )
            execution.completed_at = datetime.now(UTC)
            await session.commit()
            return
        execution.status = AI_VISIBILITY_EXECUTION_STATUS_RUNNING
        await session.commit()
        try:
            await _run_single(
                adapter=adapter,
                execution=execution,
                system_instruction=system_instruction,
                model=model,
                scoring_config=scoring_config,
            )
        except Exception as exc:  # defensive: never let one kill the run
            logger.exception("ai_visibility execution crashed: %s", execution_id)
            execution.status = AI_VISIBILITY_EXECUTION_STATUS_FAILED
            execution.error_code = AI_VISIBILITY_ERROR_PARSE
            execution.error_message = f"{type(exc).__name__}: {exc}"
            execution.completed_at = datetime.now(UTC)
        await session.commit()


async def run_benchmark(run_id: int) -> None:
    # Outer session: gate the run, capture the scalar fields workers need, and
    # collect execution IDs. It is closed before the fan-out so the concurrent
    # workers never touch it.
    async with SessionLocal() as session:
        run = await session.get(AiVisibilityRun, run_id)
        if run is None:
            return
        if run.status not in ("pending",):
            return

        if run.provider == AI_VISIBILITY_PROVIDER_GEMINI:
            api_key = ai_visibility_settings.resolved_gemini_api_key()
        elif run.provider == AI_VISIBILITY_PROVIDER_ANTHROPIC:
            api_key = ai_visibility_settings.resolved_anthropic_api_key()
        else:
            api_key = ai_visibility_settings.resolved_openrouter_api_key()
        if not api_key:
            run.status = AI_VISIBILITY_RUN_STATUS_FAILED
            run.error_message = f"{run.provider} API key is not configured"
            run.completed_at = datetime.now(UTC)
            await session.commit()
            return

        run.status = AI_VISIBILITY_RUN_STATUS_RUNNING
        await session.commit()

        system_instruction = run.system_instruction
        model = run.model
        scoring_config = ScoringConfig.from_project(run.configuration or {})

        execution_ids = list(
            (
                await session.scalars(
                    select(AiVisibilityExecution.id)
                    .where(AiVisibilityExecution.run_id == run.id)
                    .where(
                        AiVisibilityExecution.status
                        == AI_VISIBILITY_EXECUTION_STATUS_PENDING
                    )
                    .order_by(AiVisibilityExecution.randomized_position)
                )
            ).all()
        )

    # Shared read-only across tasks; each task opens its own session internally.
    adapter: (
        GeminiAnswerEngineAdapter
        | AnthropicAnswerEngineAdapter
        | OpenRouterAnswerEngineAdapter
    )
    if run.provider == AI_VISIBILITY_PROVIDER_GEMINI:
        adapter = GeminiAnswerEngineAdapter(api_key=api_key)
    elif run.provider == AI_VISIBILITY_PROVIDER_ANTHROPIC:
        adapter = AnthropicAnswerEngineAdapter(
            api_key=api_key,
            country_code=scoring_config.country_code,
        )
    else:
        adapter = OpenRouterAnswerEngineAdapter(
            api_key=api_key,
            provider_id=run.provider,
            country_code=scoring_config.country_code,
        )
    semaphore = asyncio.Semaphore(max(1, ai_visibility_settings.run_concurrency))
    # Per-run wall-clock deadline. Workers check it at their boundary and cut off
    # rather than starting another call, so a run can never sit live forever.
    deadline = time.monotonic() + ai_visibility_settings.max_run_seconds

    await asyncio.gather(
        *(
            _execute_one(
                execution_id=execution_id,
                adapter=adapter,
                system_instruction=system_instruction,
                model=model,
                scoring_config=scoring_config,
                semaphore=semaphore,
                deadline=deadline,
            )
            for execution_id in execution_ids
        )
    )

    async with SessionLocal() as session:
        run = await session.get(AiVisibilityRun, run_id)
        if run is not None:
            await _finalize_run(session, run)


async def _finalize_run(session, run: AiVisibilityRun) -> None:
    executions = list(
        (
            await session.scalars(
                select(AiVisibilityExecution).where(
                    AiVisibilityExecution.run_id == run.id
                )
            )
        ).all()
    )
    completed = sum(
        1 for e in executions if e.status == AI_VISIBILITY_EXECUTION_STATUS_COMPLETED
    )
    failed = sum(
        1 for e in executions if e.status == AI_VISIBILITY_EXECUTION_STATUS_FAILED
    )

    scoring_config = ScoringConfig.from_project(run.configuration or {})
    execution_dicts = [
        {
            "status": e.status,
            "prompt_index": e.prompt_index,
            "prompt_text_snapshot": e.prompt_text_snapshot,
            "prompt_theme_snapshot": e.prompt_theme_snapshot,
            "citations": e.citations or [],
            "score": e.score or {},
            "provider_metadata": e.provider_metadata or {},
        }
        for e in executions
    ]
    run.summary = aggregate_run(execution_dicts, scoring_config)
    run.completed_count = completed
    run.failed_count = failed

    # A killed run keeps its ``cancelled`` status; only derive a terminal status
    # for runs that finished on their own.
    if run.status != AI_VISIBILITY_RUN_STATUS_CANCELLED:
        if completed == 0:
            run.status = AI_VISIBILITY_RUN_STATUS_FAILED
        elif failed > 0:
            run.status = AI_VISIBILITY_RUN_STATUS_DEGRADED
        else:
            run.status = AI_VISIBILITY_RUN_STATUS_COMPLETED
    run.completed_at = datetime.now(UTC)
    await session.commit()
