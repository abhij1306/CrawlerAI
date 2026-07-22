"""Per-URL DB round-trip storm regressions (audit 2.3).

Covers: release-payload memoization, has_table introspection caching,
acquisition-contract upsert debounce, batched record flushes, and batched
pipeline log events.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.domain_profiles import INTERNAL_API_ENDPOINTS_PROFILE_KEY
from app.core.config.extraction_memory import EXTRACTION_RELEASE_VERSION
from app.crawl.pipeline import persistence as record_persistence
from app.crawl.pipeline import record_extraction_stage
from app.crawl.pipeline.runtime_helpers import log_pipeline_event
from app.crawl.pipeline.url_processing_context import URLProcessingContext
from app.crawl.profile import acquisition_contract
from app.crawl.profile import repository as profile_repository
from app.crawl.profile.acquisition_contract import build_success_acquisition_contract
from app.models.crawl_run import CrawlLog, CrawlRecord
from app.models.extraction_memory import ExtractionReleaseSnapshot
from app.persistence.extraction_memory import reset_release_payload_cache

pytestmark = [pytest.mark.asyncio, pytest.mark.component]


def _context(session: AsyncSession, run) -> URLProcessingContext:
    return URLProcessingContext(
        session=session,
        run=run,
        url="https://example.com/products/1",
        config=SimpleNamespace(max_records=10),
        url_timeout_seconds=120.0,
        started_at_monotonic=0.0,
        requested_fields=[],
        surface="ecommerce_detail",
    )


async def test_release_payload_loaded_once_per_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_release_payload_cache()
    snapshot = ExtractionReleaseSnapshot(
        run_id=None,
        domain="example.com",
        surface="ecommerce_detail",
        release_version=EXTRACTION_RELEASE_VERSION,
        payload={"templates": [], "sentinel": {}},
    )
    db_session.add(snapshot)
    await db_session.commit()

    real_get = db_session.get
    get_models: list[object] = []

    async def _spy_get(model, ident, **kwargs):
        get_models.append(model)
        return await real_get(model, ident, **kwargs)

    monkeypatch.setattr(db_session, "get", _spy_get)

    run = SimpleNamespace(
        id=1,
        extraction_release_snapshot_id=snapshot.id,
        settings_view=SimpleNamespace(extraction_contract=lambda: {}),
    )
    context = _context(db_session, run)

    # The full per-URL surface: selector-rule load plus repeated snapshot loads
    # (extraction pass, traversal fallback, learn-once) across the run.
    await record_extraction_stage._load_selector_rules(
        context, "https://example.com/products/1"
    )
    await record_extraction_stage._load_runtime_snapshot(context)
    await record_extraction_stage._load_runtime_snapshot(context)

    snapshot_loads = [
        model for model in get_models if model is ExtractionReleaseSnapshot
    ]
    assert len(snapshot_loads) == 1

    # Callers keep per-call mutable-copy semantics: mutations never leak into
    # the memoized payload.
    first = await record_extraction_stage._load_runtime_snapshot(context)
    first["templates"].append({"polluted": True})
    second = await record_extraction_stage._load_runtime_snapshot(context)
    assert second["templates"] == []
    assert second["_release_snapshot_id"] == str(snapshot.id)
    snapshot_loads = [
        model for model in get_models if model is ExtractionReleaseSnapshot
    ]
    assert len(snapshot_loads) == 1


async def test_has_table_introspection_cached_per_engine(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_repository.reset_domain_run_profiles_table_cache()
    real_inspect = profile_repository.inspect
    inspect_calls: list[object] = []

    def _counting_inspect(target):
        inspect_calls.append(target)
        return real_inspect(target)

    monkeypatch.setattr(profile_repository, "inspect", _counting_inspect)

    for _ in range(4):
        await profile_repository.load_domain_run_profile(
            db_session, domain="example.com", surface="ecommerce_detail"
        )
    assert len(inspect_calls) == 1

    profile_repository.reset_domain_run_profiles_table_cache()
    await profile_repository.load_domain_run_profile(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    assert len(inspect_calls) == 2


def _counting_save(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    save_calls: list[dict] = []
    real_save = acquisition_contract.save_domain_run_profile

    async def _counting(session, **kwargs):
        save_calls.append(kwargs)
        return await real_save(session, **kwargs)

    monkeypatch.setattr(acquisition_contract, "save_domain_run_profile", _counting)
    return save_calls


def _success_outcome(**overrides) -> dict:
    outcome = {
        "domain": "example.com",
        "surface": "ecommerce_detail",
        "source_run_id": 1,
        "method": "browser",
        "browser_engine": "patchright",
        "browser_diagnostics": {},
        "requested_fields": ["title"],
        "records": [{"title": "Widget", "url": "https://example.com/p/1"}],
        "persisted_count": 1,
        "verdict": "success",
        "blocked": False,
        "page_url": "https://example.com/p/1",
        "network_payloads": [],
    }
    outcome.update(overrides)
    return outcome


async def test_contract_outcome_upsert_debounced_when_unchanged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_calls = _counting_save(monkeypatch)

    await acquisition_contract.record_acquisition_contract_outcome(
        db_session, **_success_outcome()
    )
    assert len(save_calls) == 1
    await db_session.commit()

    # Identical outcome on the next URL of the run: no rewrite of the same row.
    await acquisition_contract.record_acquisition_contract_outcome(
        db_session, **_success_outcome()
    )
    assert len(save_calls) == 1

    # A real contract change still writes.
    await acquisition_contract.record_acquisition_contract_outcome(
        db_session, **_success_outcome(persisted_count=3)
    )
    assert len(save_calls) == 2

    profile = await profile_repository.load_domain_run_profile(
        db_session, domain="example.com", surface="ecommerce_detail"
    )
    assert profile is not None
    contract = profile.profile["acquisition_contract"]
    assert contract["last_quality_success"]["record_count"] == 3


async def test_learned_endpoints_merge_into_single_profile_upsert(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_calls = _counting_save(monkeypatch)

    await acquisition_contract.save_learned_acquisition_contract(
        db_session,
        domain="api.example.com",
        surface="ecommerce_detail",
        source_run_id=7,
        contract=build_success_acquisition_contract(
            method="browser",
            browser_engine="patchright",
            browser_diagnostics={},
            record_count=2,
            requested_fields=["title"],
            found_fields=["title"],
            source_run_id=7,
        ),
        internal_api_endpoints=[
            {
                "url": "https://api.example.com/products/1",
                "method": "GET",
                "endpoint_type": "product",
                "endpoint_family": "products",
                "source_run_id": 7,
            }
        ],
    )

    # One upsert persists contract + endpoints (previously two saves of the
    # same row when endpoints were learned).
    assert len(save_calls) == 1
    profile = await profile_repository.load_domain_run_profile(
        db_session, domain="api.example.com", surface="ecommerce_detail"
    )
    assert profile is not None
    endpoints = profile.profile[INTERNAL_API_ENDPOINTS_PROFILE_KEY]
    assert [endpoint["url"] for endpoint in endpoints] == [
        "https://api.example.com/products/1"
    ]
    assert profile.profile["acquisition_contract"]["last_quality_success"] is not None


async def test_log_pipeline_event_batches_rows_until_url_commit(
    db_session: AsyncSession, create_test_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_test_run(url="https://example.com/a", surface="ecommerce_detail")
    context = SimpleNamespace(
        config=SimpleNamespace(persist_logs=True),
        url="https://example.com/a",
        run=run,
        session=db_session,
    )
    counts = {"commit": 0, "flush": 0}
    real_commit = db_session.commit
    real_flush = db_session.flush

    async def _commit():
        counts["commit"] += 1
        return await real_commit()

    async def _flush():
        counts["flush"] += 1
        return await real_flush()

    monkeypatch.setattr(db_session, "commit", _commit)
    monkeypatch.setattr(db_session, "flush", _flush)

    for index in range(3):
        await log_pipeline_event(context, "info", f"event {index}")
    # No per-event flush or commit: rows ride the URL's single final commit.
    assert counts == {"commit": 0, "flush": 0}

    context.config.persist_logs = False
    await log_pipeline_event(context, "info", "dropped")

    await db_session.commit()
    rows = (
        (
            await db_session.execute(
                select(CrawlLog).where(CrawlLog.run_id == run.id).order_by(CrawlLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.message for row in rows] == ["event 0", "event 1", "event 2"]


def _acquisition(final_url: str = "https://example.com/p/1") -> SimpleNamespace:
    return SimpleNamespace(
        final_url=final_url,
        method="http",
        status_code=200,
        browser_diagnostics={},
    )


def _records(*urls: str) -> list[dict[str, object]]:
    return [
        {
            "url": url,
            "source_url": url,
            "title": f"Widget {index}",
            "price": "10.00",
        }
        for index, url in enumerate(urls)
    ]


async def test_persist_extracted_records_flushes_once_per_url(
    db_session: AsyncSession, create_test_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await create_test_run(
        url="https://example.com/p/1", surface="ecommerce_detail"
    )
    flush_calls = 0
    real_flush = db_session.flush

    async def _flush():
        nonlocal flush_calls
        flush_calls += 1
        return await real_flush()

    monkeypatch.setattr(db_session, "flush", _flush)

    records = _records(
        "https://example.com/p/1",
        "https://example.com/p/2",
        "https://example.com/p/3",
    )
    batch = await record_persistence.persist_extracted_records(
        db_session,
        run,
        records,
        acquisition_result=_acquisition(),
        url_result_id=None,
    )
    assert flush_calls == 1
    assert batch.record_count == 3
    assert batch.changed_count == 3
    # Provenance is built after the batched flush, so ids are populated.
    assert all(provenance.get("record_id") for provenance in batch.provenance)

    # An identical re-extraction stages no-change rows: one (empty) flush,
    # zero changed rows, same authoritative count.
    rerun = await record_persistence.persist_extracted_records(
        db_session,
        run,
        records,
        acquisition_result=_acquisition(),
        url_result_id=None,
    )
    assert flush_calls == 2
    assert rerun.changed_count == 0
    assert rerun.record_count == 3


async def test_persist_extracted_records_isolates_flush_failures(
    db_session: AsyncSession, create_test_run
) -> None:
    run = await create_test_run(
        url="https://example.com/p/9", surface="ecommerce_detail"
    )
    records = _records("https://example.com/p/9")

    # A dangling url_result_id violates the FK: the batch flush fails and the
    # per-record savepoint fallback skips the bad record without raising.
    failed = await record_persistence.persist_extracted_records(
        db_session,
        run,
        records,
        acquisition_result=_acquisition("https://example.com/p/9"),
        url_result_id=99999999,
    )
    assert failed.record_count == 0
    assert failed.changed_count == 0

    # The savepoints kept the URL transaction usable for subsequent writes.
    good = await record_persistence.persist_extracted_records(
        db_session,
        run,
        records,
        acquisition_result=_acquisition("https://example.com/p/9"),
        url_result_id=None,
    )
    assert good.record_count == 1
    await db_session.commit()
    stored = (
        (
            await db_session.execute(
                select(CrawlRecord).where(CrawlRecord.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1


class _FakeSavepoint:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    """Minimal session double emulating savepoint-rollback flush semantics."""

    def __init__(self, bad_url: str):
        self.bad_url = bad_url
        self.new_records: list = []
        self.persisted: list = []
        self.batch_failures_left = 1

    def add(self, record) -> None:
        self.new_records.append(record)

    def __contains__(self, record) -> bool:
        return record in self.new_records or record in self.persisted

    def expunge(self, record) -> None:
        if record in self.new_records:
            self.new_records.remove(record)

    async def scalars(self, *args, **kwargs):
        return []

    def begin_nested(self):
        return _FakeSavepoint(self)

    async def flush(self) -> None:
        if self.batch_failures_left and len(self.new_records) > 1:
            self.batch_failures_left -= 1
            raise RuntimeError("batch flush boom")
        if any(record.source_url == self.bad_url for record in self.new_records):
            raise RuntimeError("record flush boom")
        for record in list(self.new_records):
            self.persisted.append(record)
            self.new_records.remove(record)


async def test_persist_extracted_records_fallback_keeps_good_records() -> None:
    session = _FakeSession(bad_url="https://example.com/p/bad")
    run = SimpleNamespace(id=1, surface="ecommerce_detail", requested_fields=[])
    records = _records(
        "https://example.com/p/good-1",
        "https://example.com/p/bad",
        "https://example.com/p/good-2",
    )

    batch = await record_persistence.persist_extracted_records(
        session,
        run,
        records,
        acquisition_result=_acquisition("https://example.com/p/good-1"),
        url_result_id=None,
    )

    assert [record.source_url for record in batch.records] == [
        "https://example.com/p/good-1",
        "https://example.com/p/good-2",
    ]
    assert batch.changed_count == 2
    assert [record.source_url for record in session.persisted] == [
        "https://example.com/p/good-1",
        "https://example.com/p/good-2",
    ]
