from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
V2_ROOT = ROOT / "app" / "services" / "extraction_v2"
OLD_DETAIL_ROOT = ROOT / "app" / "services" / "extract" / "detail"
pytestmark = pytest.mark.unit

LOC_BUDGETS = {
    "core": 1200,
    "collectors": 2200,
    "entities": 1200,
    "validation": 800,
    "resolution": 1200,
    "materialization": 500,
}


def _loc(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _py_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.py"))


def test_extraction_v2_loc_budgets_and_file_limits() -> None:
    files = _py_files(V2_ROOT)
    assert sum(_loc(path) for path in files) <= 7100
    assert sum(_loc(path) for path in _py_files(V2_ROOT / "collectors")) <= LOC_BUDGETS["collectors"]
    assert sum(_loc(path) for path in _py_files(V2_ROOT / "entities")) <= LOC_BUDGETS["entities"]
    assert sum(_loc(path) for path in _py_files(V2_ROOT / "validation")) <= LOC_BUDGETS["validation"]
    assert sum(_loc(path) for path in _py_files(V2_ROOT / "resolution")) <= LOC_BUDGETS["resolution"]
    assert sum(_loc(path) for path in _py_files(V2_ROOT / "materialization")) <= LOC_BUDGETS["materialization"]
    assert all(_loc(path) <= 400 for path in files)


def test_extraction_v2_structural_limits() -> None:
    offenders: list[str] = []
    for path in _py_files(V2_ROOT):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if path.name in {"cleanup.py", "repair.py"}:
            offenders.append(path.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("repair_"):
                    offenders.append(f"{path.name}:{node.name}")
                if len(node.args.args) + len(node.args.kwonlyargs) > 8:
                    offenders.append(f"{path.name}:{node.name}:args")
                if node.end_lineno and node.end_lineno - node.lineno + 1 > 60:
                    offenders.append(f"{path.name}:{node.name}:loc")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("app.services.extract.detail"):
                    offenders.append(f"{path.name}:{node.module}")
    assert offenders == []


def test_old_ecommerce_detail_runtime_path_is_not_imported_by_cutover() -> None:
    text = (ROOT / "app" / "services" / "pipeline" / "extract_records.py").read_text(encoding="utf-8")
    assert "extract_ecommerce_detail_v2" in text
    assert "repair_ecommerce_detail_record_quality" not in text
    assert "drop_low_signal_zero_detail_price" not in text


def test_replaced_surface_loc_reduction_is_at_least_40_percent() -> None:
    old_loc = sum(_loc(path) for path in _py_files(OLD_DETAIL_ROOT) if "identity" not in path.parts)
    new_loc = sum(_loc(path) for path in _py_files(V2_ROOT))
    assert new_loc <= int(old_loc * 0.60)
