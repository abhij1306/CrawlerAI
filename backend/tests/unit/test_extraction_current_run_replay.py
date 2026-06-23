from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.fixtures.loader import current_run_pages_root, read_current_run_json

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class CurrentRunCase:
    page_id: str
    site: str
    has_browser_artifact: bool = True


CURRENT_RUN_CASES: tuple[CurrentRunCase, ...] = (
    CurrentRunCase("2df9a2c22fb0d693", "hm"),
    CurrentRunCase("34377e7318db5880", "levis"),
    CurrentRunCase("9e29c8a8fb73e996", "uniqlo"),
    CurrentRunCase("a59a8efd30eadf27", "new_balance"),
    CurrentRunCase("c650b8173c563508", "puma"),
    CurrentRunCase("df4dfab1e2ae4783", "zara"),
    CurrentRunCase("e1bfcab42d8e9c8a", "north_face", has_browser_artifact=False),
)


def _case_ids() -> list[str]:
    return [case.site for case in CURRENT_RUN_CASES]


def test_current_run_json_artifact_packet_is_frozen_without_html() -> None:
    pages_root = current_run_pages_root()
    assert pages_root.exists()
    assert not list(pages_root.glob("*.html"))
    assert {case.page_id for case in CURRENT_RUN_CASES} == {
        path.name.split(".", 1)[0] for path in pages_root.glob("*.trace.json")
    }
    for case in CURRENT_RUN_CASES:
        assert (pages_root / f"{case.page_id}.trace.json").exists()
        assert (pages_root / f"{case.page_id}.extraction.json").exists()
        browser_path = pages_root / f"{case.page_id}.browser.json"
        assert browser_path.exists() is case.has_browser_artifact


@pytest.mark.parametrize("case", CURRENT_RUN_CASES, ids=_case_ids())
def test_current_run_json_artifacts_have_url_and_extraction_summary(
    case: CurrentRunCase,
) -> None:
    trace = read_current_run_json(case.page_id, "trace")
    extraction = read_current_run_json(case.page_id, "extraction")
    assert trace.get("url")
    assert extraction.get("verdict") in {
        "success",
        "partial",
        "review",
        "blocked",
        "listing_detection_failed",
        "empty",
    }
    assert isinstance(extraction.get("record_count"), int)


def test_frozen_json_artifacts_preserve_original_known_failures() -> None:
    original = {
        case.site: read_current_run_json(case.page_id, "extraction")
        for case in CURRENT_RUN_CASES
    }
    assert original["hm"]["record_count"] == 0
    assert original["puma"]["record_count"] == 0
    assert original["zara"]["record_count"] == 0
    assert original["new_balance"]["verdict"] == "success"
    assert original["new_balance"]["records"][0]["public_fields"]["title"] == (
        "Oops! Something went wrong"
    )
    assert original["levis"]["records"][0]["public_fields"].get("variants") in (
        None,
        [],
    )
