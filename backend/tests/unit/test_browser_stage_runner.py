from __future__ import annotations

import asyncio

import pytest

from app.acquisition.browser_stage_runner import run_browser_stage


class _Page:
    def __init__(self) -> None:
        self.closed = asyncio.Event()

    async def close(self) -> None:
        self.closed.set()


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_after_stage_cleanup() -> None:
    page = _Page()
    started = asyncio.Event()
    unwound = asyncio.Event()

    async def operation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            unwound.set()

    caller = asyncio.create_task(
        run_browser_stage(
            stage="readiness",
            page=page,
            timeout_seconds=30,
            phase_timings_ms={},
            operation=operation,
        )
    )
    await started.wait()
    caller.cancel()

    with pytest.raises(asyncio.CancelledError):
        await caller

    assert page.closed.is_set()
    assert unwound.is_set()


@pytest.mark.asyncio
async def test_stage_timeout_remains_timeout_after_child_cancellation() -> None:
    page = _Page()
    unwound = asyncio.Event()

    async def operation() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            unwound.set()

    with pytest.raises(TimeoutError, match="Browser readiness stage exceeded"):
        await run_browser_stage(
            stage="readiness",
            page=page,
            timeout_seconds=0.01,
            phase_timings_ms={},
            operation=operation,
        )

    assert page.closed.is_set()
    assert unwound.is_set()
