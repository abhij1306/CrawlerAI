"""Unit tests for the read-only observability artifact reader (Slice 7)."""

from __future__ import annotations

import json

import pytest

from app.services.observability import artifact_reader

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _tmp_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_reader.settings, "artifacts_dir", tmp_path)
    return tmp_path


def _run_dirs(tmp_path, run_id: int):
    audit = tmp_path / "runs" / str(run_id) / "audit"
    pages = tmp_path / "runs" / str(run_id) / "pages"
    audit.mkdir(parents=True)
    pages.mkdir(parents=True)
    return audit, pages


def test_reads_flags_traces_and_diagnosis(tmp_path):
    audit, pages = _run_dirs(tmp_path, 5)
    (audit / "flags.json").write_text(
        json.dumps({"run_id": 5, "flag_count": 1, "flags": [{"code": "x"}]}),
        encoding="utf-8",
    )
    (audit / "llm_diagnosis.json").write_text(
        json.dumps({"status": "ok", "diagnosis": {"summary": "s"}}),
        encoding="utf-8",
    )
    (pages / "a.trace.json").write_text(
        json.dumps({"url": "https://e.com/p/a", "verdict": "success"}),
        encoding="utf-8",
    )

    result = artifact_reader.read_run_observability(5)
    assert result["run_id"] == 5
    assert result["flags"]["flag_count"] == 1
    assert result["llm_diagnosis"]["status"] == "ok"
    assert len(result["traces"]) == 1
    assert result["traces"][0]["url"] == "https://e.com/p/a"


def test_missing_artifacts_yield_empty_view(tmp_path):
    result = artifact_reader.read_run_observability(999)
    assert result["run_id"] == 999
    assert result["flags"] is None
    assert result["llm_diagnosis"] is None
    assert result["traces"] == []


def test_negative_run_id_is_clamped_for_path_and_payload(tmp_path):
    audit, _pages = _run_dirs(tmp_path, 0)
    (audit / "flags.json").write_text(
        json.dumps({"run_id": 0, "flag_count": 0, "flags": []}),
        encoding="utf-8",
    )

    result = artifact_reader.read_run_observability(-5)

    assert result["run_id"] == 0
    assert result["flags"]["run_id"] == 0


def test_ignores_malformed_json(tmp_path):
    audit, pages = _run_dirs(tmp_path, 7)
    (audit / "flags.json").write_text("{not json", encoding="utf-8")
    result = artifact_reader.read_run_observability(7)
    assert result["flags"] is None
