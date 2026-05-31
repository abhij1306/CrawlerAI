"""Unit tests for the observe-only LLM run diagnosis (Slice 6, Phase 2).

Validates the gating (flags + llm_enabled + config), the skip diagnostics, and
that a successful LLM call is shaped into the diagnosis artifact — all without a
real provider call (run_prompt_task is monkeypatched).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.llm.types import LLMTaskResult
from app.services.observability import run_llm_diagnosis as diag

pytestmark = pytest.mark.unit


class _SettingsView:
    def __init__(self, *, enabled: bool, has_config: bool):
        self._enabled = enabled
        self._has_config = has_config

    def llm_enabled(self) -> bool:
        return self._enabled

    def has_llm_config_snapshot(self) -> bool:
        return self._has_config


def _run(*, enabled: bool, has_config: bool, run_id: int = 1):
    return SimpleNamespace(
        id=run_id,
        url="https://e.com/p/x",
        surface="ecommerce_detail",
        requested_fields=["price", "variants"],
        result_summary={"extraction_verdict": "partial"},
        settings_view=_SettingsView(enabled=enabled, has_config=has_config),
    )


def _record():
    return SimpleNamespace(
        source_url="https://e.com/p/x",
        data={"title": "Widget", "price": "10.00"},
        raw_html_path="",
    )


_FLAGS = [{"code": "high_value_field_missing", "severity": "medium", "owner": "x.py"}]


@pytest.mark.asyncio
async def test_skips_when_no_flags():
    run = _run(enabled=True, has_config=True)
    result = await diag.diagnose_run(None, run, [_record()], [])
    assert result == {"status": "skipped", "reason": "no_flags"}


@pytest.mark.asyncio
async def test_skips_when_llm_disabled():
    run = _run(enabled=False, has_config=True)
    result = await diag.diagnose_run(None, run, [_record()], _FLAGS)
    assert result["status"] == "skipped"
    assert result["reason"] == "llm_disabled"


@pytest.mark.asyncio
async def test_skips_when_no_config_snapshot():
    run = _run(enabled=True, has_config=False)
    result = await diag.diagnose_run(None, run, [_record()], _FLAGS)
    assert result["status"] == "skipped"
    assert result["reason"] == "llm_disabled"


@pytest.mark.asyncio
async def test_ok_diagnosis_shaped_from_llm(monkeypatch):
    async def _fake_run_prompt_task(session, **kwargs):
        assert kwargs["task_type"] == "run_diagnosis"
        return LLMTaskResult(
            payload={
                "summary": "price came from js_state; variants missing",
                "field_provenance": [{"field": "price", "source": "js_state", "note": ""}],
                "likely_root_cause": "DOM tier skipped before variant cues",
                "missing_field_reasons": [
                    {"field": "variants", "source": "", "note": "dom skipped"}
                ],
            },
            provider="groq",
            model="llama-3.3-70b",
        )

    monkeypatch.setattr(diag, "run_prompt_task", _fake_run_prompt_task)
    run = _run(enabled=True, has_config=True)
    result = await diag.diagnose_run(object(), run, [_record()], _FLAGS)
    assert result["status"] == "ok"
    assert result["provider"] == "groq"
    assert result["diagnosis"]["likely_root_cause"].startswith("DOM tier skipped")


@pytest.mark.asyncio
async def test_unavailable_when_llm_errors(monkeypatch):
    async def _fake_run_prompt_task(session, **kwargs):
        return LLMTaskResult(payload=None, error_message="Error: provider down")

    monkeypatch.setattr(diag, "run_prompt_task", _fake_run_prompt_task)
    run = _run(enabled=True, has_config=True)
    result = await diag.diagnose_run(object(), run, [_record()], _FLAGS)
    assert result["status"] == "unavailable"
    assert "provider down" in result["reason"]


def test_write_diagnosis_creates_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(diag.settings, "artifacts_dir", tmp_path)
    path = diag.write_diagnosis(7, {"status": "ok", "diagnosis": {"summary": "x"}})
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert path.endswith("llm_diagnosis.json")
