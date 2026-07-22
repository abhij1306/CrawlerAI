"""Circular-dependency regression (audit 4.7).

``record_extraction_stage`` used to re-import ``extraction_loop`` lazily
inside four functions while ``extraction_loop`` imported it at module level.
The dependency is now one-directional, verified in fresh interpreters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_fresh(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_record_extraction_stage_imports_without_extraction_loop() -> None:
    result = _run_fresh(
        "import sys; "
        "import app.crawl.pipeline.record_extraction_stage; "
        "assert 'app.crawl.pipeline.extraction_loop' not in sys.modules, "
        "'record_extraction_stage must not import extraction_loop'"
    )
    assert result.returncode == 0, result.stderr


def test_pipeline_modules_import_in_either_order() -> None:
    snippets = (
        "import app.crawl.pipeline.record_extraction_stage; "
        "import app.crawl.pipeline.extraction_loop",
        "import app.crawl.pipeline.extraction_loop; "
        "import app.crawl.pipeline.record_extraction_stage",
    )
    for snippet in snippets:
        result = _run_fresh(snippet)
        assert result.returncode == 0, result.stderr
