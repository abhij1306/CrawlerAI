from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_ROOT = Path(__file__).resolve().parent
CURRENT_RUN_FIXTURE_ROOT = _FIXTURES_ROOT / "extraction" / "current_run"


def read_optional_artifact_text(
    path: str,
    *,
    fixture_subdir: str | None = None,
) -> str:
    artifact_path = Path(path)
    candidates: list[Path] = []
    if fixture_subdir:
        candidates.append(_FIXTURES_ROOT / fixture_subdir / artifact_path.name)
    candidates.extend((artifact_path, _BACKEND_ROOT / artifact_path))
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="ignore")
    pytest.skip(
        f"artifact fixture missing: {candidates[0] if candidates else artifact_path}"
    )
    raise RuntimeError("pytest.skip did not abort execution")


def current_run_pages_root() -> Path:
    return CURRENT_RUN_FIXTURE_ROOT / "pages"


def read_current_run_json(page_id: str, suffix: str) -> dict[str, Any]:
    path = current_run_pages_root() / f"{page_id}.{suffix}.json"
    if not path.exists():
        pytest.skip(f"current-run fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_current_run_html(page_id: str) -> str:
    path = current_run_pages_root() / f"{page_id}.html"
    if not path.exists():
        pytest.skip(f"current-run HTML fixture missing: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")
