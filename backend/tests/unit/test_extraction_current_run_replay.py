from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pytest

from app.extraction import Surface, extract
from app.extraction.contracts import ExtractionResult
from app.extraction.replay import fixture_request_from_inputs
from tests.fixtures.loader import (
    current_run_pages_root,
    read_current_run_html,
    read_current_run_json,
)

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class CurrentRunCase:
    page_id: str
    site: str


CURRENT_RUN_CASES: tuple[CurrentRunCase, ...] = (
    CurrentRunCase("19c6747872b3ba4a", "under_armour"),
    CurrentRunCase("2df9a2c22fb0d693", "hm"),
    CurrentRunCase("34377e7318db5880", "levis"),
    CurrentRunCase("9e29c8a8fb73e996", "uniqlo"),
    CurrentRunCase("a59a8efd30eadf27", "new_balance"),
    CurrentRunCase("c650b8173c563508", "puma"),
    CurrentRunCase("df4dfab1e2ae4783", "zara"),
    CurrentRunCase("e1bfcab42d8e9c8a", "north_face"),
)


def _case_ids() -> list[str]:
    return [case.site for case in CURRENT_RUN_CASES]


@lru_cache(maxsize=None)
def _replay(page_id: str) -> ExtractionResult:
    trace = read_current_run_json(page_id, "trace")
    html = read_current_run_html(page_id)
    return extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            str(trace["url"]),
            requested_url=str(trace["url"]),
        )
    )


def _record(result: ExtractionResult) -> dict[str, object]:
    return (
        result.records[0].model_dump(mode="json", exclude_none=True)
        if result.records
        else {}
    )


def _variants(result: ExtractionResult) -> list[object]:
    variants = _record(result).get("variants")
    return variants if isinstance(variants, list) else []


def test_current_run_fixture_corpus_is_frozen() -> None:
    pages_root = current_run_pages_root()
    assert pages_root.exists()
    assert {case.page_id for case in CURRENT_RUN_CASES} == {
        path.name.split(".", 1)[0] for path in pages_root.glob("*.html")
    }
    for case in CURRENT_RUN_CASES:
        assert (pages_root / f"{case.page_id}.html").exists()
        assert (pages_root / f"{case.page_id}.trace.json").exists()
        assert (pages_root / f"{case.page_id}.extraction.json").exists()


@pytest.mark.parametrize("case", CURRENT_RUN_CASES, ids=_case_ids())
def test_current_run_replays_without_network(case: CurrentRunCase) -> None:
    result = _replay(case.page_id)
    assert result.surface == Surface.ECOMMERCE_DETAIL
    assert result.evidence
    assert result.decisions
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["evidence"]
    assert payload["decisions"]


def test_frozen_source_artifacts_preserve_original_known_failures() -> None:
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
    assert original["under_armour"]["records"][0]["public_fields"].get("variants") in (
        None,
        [],
    )
    assert original["levis"]["records"][0]["public_fields"].get("variants") in (None, [])


def test_under_armour_and_levis_variants_survive_current_replay() -> None:
    assert _variants(_replay("19c6747872b3ba4a"))
    assert _variants(_replay("34377e7318db5880"))


def test_hm_selected_product_evidence_does_not_empty_current_replay() -> None:
    result = _replay("2df9a2c22fb0d693")
    assert result.verdict in {"success", "partial", "review"}
    assert result.records


def test_uniqlo_explicit_variants_do_not_disappear() -> None:
    assert _variants(_replay("9e29c8a8fb73e996"))


def test_puma_one_axis_variants_do_not_disappear() -> None:
    variants = _variants(_replay("c650b8173c563508"))
    assert variants
    assert all(isinstance(row, dict) and row.get("color") for row in variants)
    assert any(isinstance(row, dict) and row.get("price") for row in variants)


def test_new_balance_shell_does_not_succeed() -> None:
    result = _replay("a59a8efd30eadf27")
    assert result.verdict != "success"
    assert not result.records
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


@pytest.mark.parametrize(
    ("page_id", "site"),
    (("c650b8173c563508", "puma"), ("df4dfab1e2ae4783", "zara")),
)
def test_selected_product_evidence_does_not_silently_empty_output(
    page_id: str,
    site: str,
) -> None:
    result = _replay(page_id)
    assert result.evidence, site
    assert result.records, site
    assert result.verdict in {"success", "partial", "review"}


def test_north_face_primary_image_is_not_benefit_icon() -> None:
    image_url = str(_record(_replay("e1bfcab42d8e9c8a")).get("image_url") or "")
    assert "benefit-icon" not in image_url


def test_serialized_result_has_consistent_replay_counts() -> None:
    for case in CURRENT_RUN_CASES:
        result = _replay(case.page_id)
        payload = result.model_dump(mode="json", exclude_none=True)
        assert len(result.evidence) == len(payload.get("evidence") or [])
        assert len(result.decisions) == len(payload.get("decisions") or [])
        assert payload.get("surface") == Surface.ECOMMERCE_DETAIL.value
