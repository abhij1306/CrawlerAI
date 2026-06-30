from __future__ import annotations

import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.crawl_run import CrawlUrlResult
from app.crawl.crud import create_crawl_run


@pytest.fixture
async def diagnostics_api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _make_run(db_session, test_user):
    return await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.component
async def test_result_diagnosis_endpoint_returns_persisted_artifact(
    diagnostics_api_client: AsyncClient,
    db_session,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user)
    url_result = CrawlUrlResult(
        run_id=run.id,
        requested_url="https://example.com/products/widget",
        normalized_url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    db_session.add(url_result)
    await db_session.commit()
    await db_session.refresh(url_result)

    diagnosis = {"schema_version": "diagnose.v2", "verdict": "partial", "fields": []}
    _write_json(
        tmp_path
        / "runs"
        / str(run.id)
        / "results"
        / str(url_result.id)
        / "diagnose.json",
        diagnosis,
    )

    response = await diagnostics_api_client.get(
        f"/api/crawls/{run.id}/results/{url_result.id}/diagnose.json"
    )

    assert response.status_code == 200
    assert response.json() == diagnosis


@pytest.mark.asyncio
@pytest.mark.component
async def test_result_diagnosis_404_when_artifact_missing(
    diagnostics_api_client: AsyncClient,
    db_session,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user)
    url_result = CrawlUrlResult(
        run_id=run.id,
        requested_url="https://example.com/p",
        normalized_url="https://example.com/p",
        surface="ecommerce_detail",
    )
    db_session.add(url_result)
    await db_session.commit()
    await db_session.refresh(url_result)

    response = await diagnostics_api_client.get(
        f"/api/crawls/{run.id}/results/{url_result.id}/diagnose.json"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.component
async def test_result_diagnosis_404_when_url_result_belongs_to_other_run(
    diagnostics_api_client: AsyncClient,
    db_session,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user)
    other_run = await _make_run(db_session, test_user)
    url_result = CrawlUrlResult(
        run_id=other_run.id,
        requested_url="https://example.com/p",
        normalized_url="https://example.com/p",
        surface="ecommerce_detail",
    )
    db_session.add(url_result)
    await db_session.commit()
    await db_session.refresh(url_result)

    response = await diagnostics_api_client.get(
        f"/api/crawls/{run.id}/results/{url_result.id}/diagnose.json"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_report_endpoint_returns_persisted_report(
    diagnostics_api_client: AsyncClient,
    db_session,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user)
    report = {
        "schema_version": "run-report.v1",
        "run_id": run.id,
        "root_cause_count": 1,
        "root_causes": [
            {"root_cause": "field:price:captured_but_rejected", "count": 1}
        ],
    }
    _write_json(tmp_path / "runs" / str(run.id) / "report.json", report)

    response = await diagnostics_api_client.get(f"/api/crawls/{run.id}/report.json")

    assert response.status_code == 200
    assert response.json() == report


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_report_endpoint_builds_on_demand_when_unwritten(
    diagnostics_api_client: AsyncClient,
    db_session,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user)
    # No report.json on disk, but a diagnose.json with a rejected field exists.
    _write_json(
        tmp_path / "runs" / str(run.id) / "results" / "1" / "diagnose.json",
        {
            "schema_version": "diagnose.v2",
            "fields": [{"field": "price", "status": "captured_but_rejected"}],
            "variants": {"dropped": []},
        },
    )

    response = await diagnostics_api_client.get(f"/api/crawls/{run.id}/report.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "run-report.v1"
    assert payload["root_cause_count"] == 1
    assert (
        payload["root_causes"][0]["root_cause"] == "field:price:captured_but_rejected"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_diagnostics_endpoints_404_for_inaccessible_run(
    diagnostics_api_client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    missing_run_id = 999_999

    report_response = await diagnostics_api_client.get(
        f"/api/crawls/{missing_run_id}/report.json"
    )
    diagnose_response = await diagnostics_api_client.get(
        f"/api/crawls/{missing_run_id}/results/1/diagnose.json"
    )

    assert report_response.status_code == 404
    assert diagnose_response.status_code == 404
