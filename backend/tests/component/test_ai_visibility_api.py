"""Component tests for AI-visibility API: scoping, key hygiene, exports."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_visibility import exports, service
from app.ai_visibility.constants import BEST_AND_LESS_PROJECT, BEST_AND_LESS_PROMPTS
from app.core.dependencies import get_current_user, get_db
from app.main import app

pytestmark = [pytest.mark.component, pytest.mark.asyncio]


async def test_best_and_less_preset_comes_from_backend_owner(
    ai_visibility_client: AsyncClient,
) -> None:
    response = await ai_visibility_client.get(
        "/api/ai-visibility/presets/best-and-less"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_mode"] == "controlled_localized"
    assert body["language_code"] == "en-AU"
    # Exact-match membership (not substring) so static analysis doesn't read
    # this as URL-substring sanitization.
    assert any(
        domain == "bestlesscomau.zendesk.com" for domain in body["unintended_domains"]
    )
    assert len(body["prompts"]) == 25


async def test_provider_status_lists_direct_and_openrouter_surfaces(
    ai_visibility_client: AsyncClient,
) -> None:
    response = await ai_visibility_client.get("/api/ai-visibility/providers")
    assert response.status_code == 200
    providers = {item["provider"]: item for item in response.json()}
    assert set(providers) == {
        "gemini",
        "anthropic",
        "openrouter_openai",
        "openrouter_anthropic",
    }
    assert providers["openrouter_openai"]["surface"] == (
        "openrouter_native_grounded_api"
    )
    assert providers["openrouter_anthropic"]["model"].startswith("anthropic/")
    # Native Claude surface is distinct from the OpenRouter-proxied one.
    assert providers["anthropic"]["surface"] == "anthropic_native_grounded_api"
    assert providers["anthropic"]["model"] == "claude-sonnet-4-6"
    assert providers["anthropic"]["supports_search_fanout"] is True


@pytest.fixture(autouse=True)
def _no_background_runner(monkeypatch: pytest.MonkeyPatch):
    """Neutralize the fire-and-forget benchmark task.

    Starlette runs ``BackgroundTasks`` after the response, and ``run_benchmark``
    opens the *global* ``SessionLocal`` (real schema, live network) rather than
    the per-test translated schema. These tests only assert scheduling/planning,
    so the real runner must not execute.
    """

    async def _noop(run_id: int) -> None:  # pragma: no cover - trivial
        return None

    monkeypatch.setattr("app.api.ai_visibility.run_benchmark", _noop)


@pytest.fixture
async def ai_visibility_client(db_session, test_user):
    """Test client with dependency overrides."""

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


async def test_provider_configured_flag(ai_visibility_client: AsyncClient) -> None:
    """Provider endpoint returns configured flag (never the key)."""
    response = await ai_visibility_client.get("/api/ai-visibility/providers")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) == 4
    provider = next(item for item in providers if item["provider"] == "gemini")
    assert provider["provider"] == "gemini"
    assert "configured" in provider
    assert provider["supports_search_fanout"] is True
    assert provider["supports_citations"] is True
    # Key never in response
    assert "api_key" not in provider
    assert "key" not in provider
    assert "GEMINI_API_KEY" not in str(response.content)


async def test_project_ownership_scoping(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """Non-admin users see only their own projects."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:3]}
    project = await service.create_project(db_session, user=test_user, payload=payload)

    # Owner sees it
    response = await ai_visibility_client.get("/api/ai-visibility/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["id"] == project.id

    # Owner retrieves it
    get_response = await ai_visibility_client.get(
        f"/api/ai-visibility/projects/{project.id}"
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == project.id


async def test_run_creates_executions(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """POST /runs creates N executions and returns 202."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:5]}
    project = await service.create_project(db_session, user=test_user, payload=payload)

    response = await ai_visibility_client.post(
        "/api/ai-visibility/runs",
        json={"project_id": project.id, "repetitions": 2},
    )
    assert response.status_code == 202
    run_data = response.json()
    assert run_data["requested_count"] == 10
    assert run_data["status"] == "pending"

    # Run detail includes executions
    detail_response = await ai_visibility_client.get(
        f"/api/ai-visibility/runs/{run_data['id']}"
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert len(detail["executions"]) == 10


async def test_key_never_in_any_serialized_response(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """API key never appears in any response, snapshot, or export."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:2]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )

    # Manually set a request_snapshot on one execution to simulate what the
    # runner would persist, so we can verify the snapshot content is safe.
    executions = await service.list_executions(db_session, run=run)
    if executions:
        executions[0].request_snapshot = {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "input": "affordable school uniforms",
            "system_instruction": "...",
            "tools": ["google_search"],
            "store": False,
            "stateless": True,
        }
        await db_session.commit()

    # Run response
    run_response = await ai_visibility_client.get(f"/api/ai-visibility/runs/{run.id}")
    run_body = run_response.content.decode()
    assert "api_key" not in run_body.lower()
    assert "GEMINI_API_KEY" not in run_body
    assert "x-goog-api-key" not in run_body

    # Executions list
    exec_response = await ai_visibility_client.get(
        f"/api/ai-visibility/runs/{run.id}/executions"
    )
    exec_body = exec_response.content.decode()
    assert "api_key" not in exec_body.lower()

    # Individual execution with snapshot
    if executions:
        detail_response = await ai_visibility_client.get(
            f"/api/ai-visibility/executions/{executions[0].id}"
        )
        detail_body = detail_response.content.decode()
        assert "api_key" not in detail_body.lower()
        # request_snapshot must prove store=false but never contain the key
        snapshot = detail_response.json().get("request_snapshot", {})
        assert snapshot.get("store") is False
        assert snapshot.get("stateless") is True
        assert "api_key" not in str(snapshot).lower()


async def test_export_csv_download(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """CSV export has correct headers and content-disposition."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:2]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )

    response = await ai_visibility_client.get(
        f"/api/ai-visibility/runs/{run.id}/export.csv"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert "run_id,prompt_index" in body
    assert "api_key" not in body.lower()


async def test_export_markdown_contains_methodology(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """Markdown export includes the methodology block."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:2]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )

    response = await ai_visibility_client.get(
        f"/api/ai-visibility/runs/{run.id}/export.md"
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    body = response.text
    assert "## Methodology" in body
    assert "stateless" in body.lower()
    assert "store=false" in body
    assert "reproducible API surface" in body
    assert "api_key" not in body.lower()


async def test_empty_prompts_rejected(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    """Creating a run from a project with no prompts returns 400."""
    payload = {**BEST_AND_LESS_PROJECT, "prompts": []}
    project = await service.create_project(db_session, user=test_user, payload=payload)

    response = await ai_visibility_client.post(
        "/api/ai-visibility/runs",
        json={"project_id": project.id, "repetitions": 1},
    )
    assert response.status_code == 400
    assert "no prompts" in response.json()["detail"]


async def test_terminal_run_can_be_deleted_from_history(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:1]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    run.status = "completed"
    await db_session.commit()

    response = await ai_visibility_client.delete(f"/api/ai-visibility/runs/{run.id}")
    assert response.status_code == 204
    missing = await ai_visibility_client.get(f"/api/ai-visibility/runs/{run.id}")
    assert missing.status_code == 404


async def test_active_run_cannot_be_deleted(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:1]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    response = await ai_visibility_client.delete(f"/api/ai-visibility/runs/{run.id}")
    assert response.status_code == 409


async def test_cancel_active_run_returns_cancelled(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:2]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    run.status = "running"
    await db_session.commit()

    response = await ai_visibility_client.post(
        f"/api/ai-visibility/runs/{run.id}/cancel"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    # Unfinished executions are terminalized so the run stops showing as live.
    detail = await ai_visibility_client.get(f"/api/ai-visibility/runs/{run.id}")
    statuses = {e["status"] for e in detail.json()["executions"]}
    assert statuses == {"cancelled"}

    # And the killed run can now be deleted (kill-then-delete).
    deleted = await ai_visibility_client.delete(f"/api/ai-visibility/runs/{run.id}")
    assert deleted.status_code == 204


async def test_cancel_terminal_run_conflicts(
    ai_visibility_client: AsyncClient, db_session, test_user
) -> None:
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:1]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    run.status = "completed"
    await db_session.commit()

    response = await ai_visibility_client.post(
        f"/api/ai-visibility/runs/{run.id}/cancel"
    )
    assert response.status_code == 409


async def test_cancel_unknown_run_returns_404(
    ai_visibility_client: AsyncClient,
) -> None:
    response = await ai_visibility_client.post("/api/ai-visibility/runs/999999/cancel")
    assert response.status_code == 404


async def test_export_csv_neutralizes_spreadsheet_formula_cells() -> None:
    """Prompt/score text that starts with a spreadsheet formula marker is quoted."""
    run = SimpleNamespace(id=7)
    execution = SimpleNamespace(
        prompt_index=0,
        repetition=1,
        prompt_text_snapshot="=HYPERLINK(\"https://evil.example\")",
        prompt_theme_snapshot="brand",
        prompt_intent_snapshot=None,
        randomized_position=0,
        status="completed",
        search_used=True,
        score={"citation_count": 1, "prompt_class": "-branded"},
        search_events=[{"query": "@inject"}],
        citations=[{"domain": "example.com"}],
        latency_ms=12,
        error_code=None,
    )

    body = exports.run_to_csv(run, [execution])

    data_line = body.strip().splitlines()[1]
    for cell in data_line.split(","):
        assert not cell.startswith(("=", "+", "@", "\t", "\r"))
    assert "'=HYPERLINK(" in body
    assert "'-branded" in body
