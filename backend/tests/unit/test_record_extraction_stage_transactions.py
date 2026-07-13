from __future__ import annotations

import inspect

import pytest

from app.crawl.pipeline import record_extraction_stage


@pytest.mark.unit
def test_model_invocation_does_not_background_shared_session_logging() -> None:
    """A worker-thread callback must never borrow the URL worker AsyncSession."""
    source = inspect.getsource(record_extraction_stage)

    assert "_ObservedModelAdapter" not in source
    assert "loop.call_soon_threadsafe" not in source
    assert "Generalized model invocation started" not in source
