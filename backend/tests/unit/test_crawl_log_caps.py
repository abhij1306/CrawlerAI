"""Unit tests for crawl log DB caps without Redis (audit 2.10)."""

from __future__ import annotations

import pytest

import app.core.redis as app_redis
from app.crawl import events

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _clear_fallback_counters():
    events._FALLBACK_DB_LOG_COUNTS.clear()
    events._FALLBACK_URL_PROGRESS_COUNTS.clear()
    yield
    events._FALLBACK_DB_LOG_COUNTS.clear()
    events._FALLBACK_URL_PROGRESS_COUNTS.clear()


@pytest.fixture
def redis_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_redis.settings, "redis_state_enabled", False)


async def test_fallback_enforces_db_cap_without_redis(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 3)

    decisions = [
        await events._should_persist_log("info", 101, "ordinary log line")
        for _ in range(5)
    ]

    assert decisions == [True, True, True, False, False]


async def test_fallback_counts_warning_and_error_toward_cap(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 2)

    decisions = [
        await events._should_persist_log(level, 102, "something notable")
        for level in ("warning", "error", "info")
    ]

    assert decisions == [True, True, False]


async def test_fallback_samples_url_progress_logs_one_in_n(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_url_progress_sample_rate", 4)
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 100)

    decisions = [
        await events._should_persist_log(
            "info", 103, f"Processing URL {index}/10: https://example.com/p{index}"
        )
        for index in range(1, 9)
    ]

    assert decisions == [True, False, False, False, True, False, False, False]
    # Progress sampling uses its own counter; the DB-row cap counter is untouched.
    assert events._FALLBACK_DB_LOG_COUNTS == {}
    assert events._FALLBACK_URL_PROGRESS_COUNTS == {103: 8}


async def test_fallback_below_min_level_skips_without_counting(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_min_level", "info")

    assert await events._should_persist_log("debug", 104, "noisy debug") is False
    assert events._FALLBACK_DB_LOG_COUNTS == {}


async def test_fallback_counters_are_bounded_with_oldest_run_eviction(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        events.crawler_runtime_settings,
        crawl_log_fallback_counter_max_entries=2,
    )
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 100)

    for run_id in (105, 106, 107):
        assert await events._should_persist_log("info", run_id, "line") is True

    assert list(events._FALLBACK_DB_LOG_COUNTS) == [106, 107]


async def test_clear_url_progress_counter_resets_fallback_counts(
    redis_disabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 1)

    assert await events._should_persist_log("info", 108, "line") is True
    assert await events._should_persist_log("info", 108, "line") is False

    events.clear_url_progress_counter(108)

    assert await events._should_persist_log("info", 108, "line") is True


async def test_redis_path_preferred_when_available() -> None:
    # The conftest FakeRedis is enabled, so the Redis counter path is taken and
    # the in-process fallback counters stay untouched.
    assert await events._should_persist_log("info", 109, "line") is True
    assert events._FALLBACK_DB_LOG_COUNTS == {}


async def test_serialized_event_has_id_and_created_at_without_refresh(
    db_session,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "crawl_log_db_max_rows_per_run", 100)
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    event = await events.append_log_event(
        run.id, "info", "persisted line", session=db_session
    )

    assert event["id"] is not None
    assert isinstance(event["id"], int)
    assert event["run_id"] == run.id
    assert event["level"] == "info"
    assert event["message"] == "persisted line"
    assert event["created_at"] is not None
