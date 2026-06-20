from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.acquisition.contracts import AttemptResult, AttemptSpec


@dataclass(frozen=True, slots=True)
class AttemptExecution:
    spec: AttemptSpec
    url: str
    deadline: datetime

    @property
    def timeout_seconds(self) -> float:
        remaining = max(0.001, (self.deadline - datetime.now(UTC)).total_seconds())
        return min(self.spec.timeout_seconds, remaining)


TransportAdapter = Callable[[AttemptExecution], Awaitable[AttemptResult]]


class AttemptExecutor:
    def __init__(self, adapters: Mapping[str, TransportAdapter]) -> None:
        self._adapters = dict(adapters)

    async def execute(
        self,
        spec: AttemptSpec,
        *,
        url: str,
        deadline: datetime,
    ) -> AttemptResult:
        started_at = datetime.now(UTC)
        if started_at >= deadline:
            return AttemptResult(
                attempt_id=spec.attempt_id,
                outcome="skipped",
                started_at=started_at,
                completed_at=started_at,
                error="global_deadline_exhausted",
            )
        adapter = self._adapters.get(spec.transport)
        if adapter is None:
            return AttemptResult(
                attempt_id=spec.attempt_id,
                outcome="error",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"transport_adapter_missing:{spec.transport}",
            )
        execution = AttemptExecution(spec=spec, url=url, deadline=deadline)
        try:
            async with asyncio.timeout(execution.timeout_seconds):
                return await adapter(execution)
        except TimeoutError:
            return AttemptResult(
                attempt_id=spec.attempt_id,
                outcome="error",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error="attempt_deadline_exhausted",
            )
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            return AttemptResult(
                attempt_id=spec.attempt_id,
                outcome="error",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=f"{type(exc).__name__}: {exc}",
            )
