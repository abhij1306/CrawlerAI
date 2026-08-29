from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.run_events import (
    RUN_EVENT_DEFINITIONS,
    RUN_EVENT_REASON_OUTCOMES,
    RUN_EVENT_REASON_SEVERITIES,
    RUN_EVENT_VERDICT_OUTCOMES,
    RunEventDefinition,
    RunEventKind,
    RunEventOutcome,
    RunEventSeverity,
    RunEventUrlPolicy,
)
from app.core.database import SessionLocal
from app.models.crawl_run import CrawlRun, RunEvent

logger = logging.getLogger(__name__)

JsonValue: TypeAlias = (
    str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None
)


@dataclass(frozen=True, slots=True)
class RunEventFact:
    kind: RunEventKind
    url: str | None = None
    url_scope_id: str | None = None
    reason_code: str | None = None
    facts: Mapping[str, JsonValue] = field(default_factory=dict)


def url_scope_id(index: int) -> str:
    if index < 1:
        raise ValueError("URL scope index must be positive")
    return f"url:{index}"


def _validate_json_value(value: object, *, path: str = "facts") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise ValueError(f"{path} must contain finite numbers")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} object keys must be non-empty strings")
            _validate_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains unsupported value {type(value).__name__}")


def _validate_url_scope(fact: RunEventFact, definition: RunEventDefinition) -> None:
    url = str(fact.url or "").strip() or None
    scope = str(fact.url_scope_id or "").strip() or None
    if definition.url_policy == RunEventUrlPolicy.REQUIRED:
        if url is None or scope is None:
            raise ValueError(f"{fact.kind.value} requires URL and URL scope")
    elif url is not None or scope is not None:
        raise ValueError(f"{fact.kind.value} is run-scoped and forbids URL scope")


def _validated_reason_code(
    fact: RunEventFact, definition: RunEventDefinition
) -> str | None:
    reason_code = str(fact.reason_code or "").strip() or None
    if definition.reason_codes:
        if reason_code not in definition.reason_codes:
            allowed = ", ".join(sorted(definition.reason_codes))
            raise ValueError(f"{fact.kind.value} reason_code must be one of: {allowed}")
    elif reason_code is not None:
        raise ValueError(f"{fact.kind.value} does not accept reason_code")
    return reason_code


def _validated_facts(
    fact: RunEventFact, definition: RunEventDefinition
) -> dict[str, JsonValue]:
    facts = dict(fact.facts)
    fact_keys = frozenset(facts)
    missing = definition.required_facts - fact_keys
    unknown = fact_keys - definition.required_facts - definition.optional_facts
    if missing:
        raise ValueError(
            f"{fact.kind.value} missing required facts: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ValueError(
            f"{fact.kind.value} received unknown facts: {', '.join(sorted(unknown))}"
        )
    _validate_json_value(facts)
    return facts


def _validated_fact(fact: RunEventFact) -> tuple[dict[str, JsonValue], str | None]:
    if not isinstance(fact.kind, RunEventKind):
        raise TypeError("Run Event kind must be a RunEventKind")
    definition = RUN_EVENT_DEFINITIONS[fact.kind]
    _validate_url_scope(fact, definition)
    reason_code = _validated_reason_code(fact, definition)
    facts = _validated_facts(fact, definition)
    return facts, reason_code


def _metadata(
    fact: RunEventFact,
    facts: Mapping[str, JsonValue],
    reason_code: str | None,
) -> tuple[RunEventSeverity, RunEventOutcome]:
    definition = RUN_EVENT_DEFINITIONS[fact.kind]
    severity = RUN_EVENT_REASON_SEVERITIES.get(
        (fact.kind, reason_code or ""), definition.severity
    )
    outcome = RUN_EVENT_REASON_OUTCOMES.get(
        (fact.kind, reason_code or ""), definition.outcome
    )
    if fact.kind in {RunEventKind.RUN_COMPLETED, RunEventKind.URL_COMPLETED}:
        verdict = str(facts.get("verdict") or "").strip().lower()
        outcome = RUN_EVENT_VERDICT_OUTCOMES.get(verdict, RunEventOutcome.FAILED)
        if outcome == RunEventOutcome.FAILED:
            severity = RunEventSeverity.ERROR
        elif outcome in {RunEventOutcome.PARTIAL, RunEventOutcome.BLOCKED}:
            severity = RunEventSeverity.WARNING
    return severity, outcome


class RunEventTimeline:
    """Append and read the immutable operator timeline through one deep interface."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        run_id: int,
        fact: RunEventFact,
        session: AsyncSession | None = None,
    ) -> RunEvent | None:
        if int(run_id) < 1:
            raise ValueError("Run Event run_id must be positive")
        facts, reason_code = _validated_fact(fact)
        severity, outcome = _metadata(fact, facts, reason_code)
        if session is not None:
            try:
                async with session.begin_nested():
                    return await self._insert(
                        session,
                        run_id=int(run_id),
                        fact=fact,
                        facts=facts,
                        reason_code=reason_code,
                        severity=severity,
                        outcome=outcome,
                    )
            except SQLAlchemyError:
                logger.warning(
                    "Run Event persistence unavailable",
                    exc_info=True,
                    extra={"run_id": int(run_id), "kind": fact.kind.value},
                )
                return None

        async with self._session_factory() as detached_session:
            try:
                row = await self._insert(
                    detached_session,
                    run_id=int(run_id),
                    fact=fact,
                    facts=facts,
                    reason_code=reason_code,
                    severity=severity,
                    outcome=outcome,
                )
                await detached_session.commit()
                return row
            except SQLAlchemyError:
                await detached_session.rollback()
                logger.warning(
                    "Run Event persistence unavailable",
                    exc_info=True,
                    extra={"run_id": int(run_id), "kind": fact.kind.value},
                )
                return None

    async def _insert(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        fact: RunEventFact,
        facts: dict[str, JsonValue],
        reason_code: str | None,
        severity: RunEventSeverity,
        outcome: RunEventOutcome,
    ) -> RunEvent | None:
        definition = RUN_EVENT_DEFINITIONS[fact.kind]
        sequence = await session.scalar(
            update(CrawlRun)
            .where(CrawlRun.id == run_id)
            .values(
                run_event_sequence=CrawlRun.run_event_sequence + 1,
                updated_at=CrawlRun.updated_at,
            )
            .returning(CrawlRun.run_event_sequence)
        )
        if sequence is None:
            logger.info(
                "Run Event dropped because run no longer exists",
                extra={"run_id": run_id, "kind": fact.kind.value},
            )
            return None
        row = RunEvent(
            run_id=run_id,
            sequence=int(sequence),
            kind=fact.kind.value,
            stage=definition.stage.value if definition.stage is not None else None,
            url=(str(fact.url).strip() or None) if fact.url is not None else None,
            url_scope_id=(
                str(fact.url_scope_id).strip() or None
                if fact.url_scope_id is not None
                else None
            ),
            severity=severity.value,
            outcome=outcome.value,
            reason_code=reason_code,
            facts=facts,
        )
        session.add(row)
        await session.flush()
        return row

    async def list_after(
        self,
        *,
        run_id: int,
        after_sequence: int | None = None,
        limit: int = 500,
    ) -> list[RunEvent]:
        if int(run_id) < 1:
            raise ValueError("Run Event run_id must be positive")
        if after_sequence is not None and int(after_sequence) < 0:
            raise ValueError("Run Event cursor cannot be negative")
        if not 1 <= int(limit) <= 2000:
            raise ValueError("Run Event limit must be between 1 and 2000")
        query = (
            select(RunEvent)
            .where(RunEvent.run_id == int(run_id))
            .order_by(RunEvent.sequence.asc())
            .limit(int(limit))
        )
        if after_sequence is not None:
            query = query.where(RunEvent.sequence > int(after_sequence))
        async with self._session_factory() as session:
            result = await session.execute(query)
            return list(result.scalars().all())


run_event_timeline = RunEventTimeline(SessionLocal)


__all__ = [
    "JsonValue",
    "RunEventFact",
    "RunEventTimeline",
    "run_event_timeline",
    "url_scope_id",
]
