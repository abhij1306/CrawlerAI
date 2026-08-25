from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from typing import Any

import pytest

from harness import artifact_quality_cases as quality_cases


class _Record:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, **_: object) -> dict[str, Any]:
        return self.payload


def _references() -> dict[str, Any]:
    cases = [
        {
            "id": case_id,
            "url": f"https://shop{case_id}.example/products/{case_id}",
            "expected": {"title": f"Product {case_id}"},
        }
        for case_id in range(1, 83)
    ]
    cases[0].update(
        {
            "expected": {
                "title": "Product 1",
                "price": "10.00",
                "currency": "USD",
                "material": "Cotton",
                "size_options": ["M"],
                "selected_fit": "Classic",
            },
            "constraints": {"price": {"value": "9.00", "mode": "volatile"}},
            "forbidden": {"title": ["Sibling Product"]},
        }
    )
    cases[23]["url"] = "https://www.zara.com/product.html?v1=123"
    cases[61]["url"] = "https://www.zara.com/product.html"
    defect_cases = [
        {
            "id": case_id,
            "issues": ["DEFECT"],
        }
        for case_id in range(1, 76)
    ]
    area_shape = {
        "product_identity_and_page_state": (4, range(48, 52)),
        "selected_variant_state": (49, range(2, 48)),
        "commercial_fields": (42, range(1, 22)),
        "variants_and_options": (14, range(52, 64)),
        "product_identifiers": (13, range(64, 76)),
        "core_identity_fields": (16, range(48, 64)),
        "attributes": (59, range(2, 44)),
        "reviews": (60, range(45, 76)),
    }
    areas = [
        {
            "area": area,
            "defects": defect_count,
            "affected_cases": len(tuple(case_ids)),
            "case_ids": list(case_ids),
            "top_fields": [{"field": "fixture", "count": defect_count}],
        }
        for area, (defect_count, case_ids) in area_shape.items()
    ]
    return {
        "evaluation": {
            "metadata": {"cases": 82, "version": "3.2"},
            "cases": cases,
        },
        "defects": {
            "metadata": {"version": "3.2"},
            "summary": {"cases": 82, "failing_cases": 75, "defects": 257},
            "problem_areas": areas,
            "cases": defect_cases,
        },
    }


def _write_capture(
    backend_root: Path,
    *,
    run_id: str,
    result_id: int,
    url: str,
) -> Path:
    root = backend_root / "artifacts" / "runs" / run_id / "results" / str(result_id)
    root.mkdir(parents=True)
    (root / "page.html").write_text(f"<h1>{url}</h1>", encoding="utf-8")
    (root / "record.json").write_text('{"must":"not be input"}', encoding="utf-8")
    (root / "diagnose.json").write_text(
        json.dumps({"acquisition": {"final_url": url}}), encoding="utf-8"
    )
    return root


def _write_all_captures(backend_root: Path, references: dict[str, Any]) -> None:
    for case in references["evaluation"]["cases"]:
        _write_capture(
            backend_root,
            run_id="1",
            result_id=int(case["id"]),
            url=str(case["url"]),
        )


def _fake_result(request: object) -> SimpleNamespace:
    requested_url = str(request.capture.requested_url)
    host = (urlsplit(requested_url).hostname or "").casefold()
    if host == "zara.com" or host.endswith(".zara.com"):
        case_id = 24 if "v1=" in requested_url else 62
    else:
        case_id = int(requested_url.rstrip("/").split("/")[-1].split("?")[0])
    payload: dict[str, Any] = {
        "title": f"Product {case_id}",
        "url": requested_url,
        "_lineage": {"title": {"evidence_ids": ["title"]}},
    }
    if case_id == 1:
        payload.update(
            {
                "price": "11.00",
                "currency": "USD",
                "materials": ["Cotton"],
                "variant_count": 1,
                "variants": [{"size": "M", "fit": "Classic"}],
            }
        )
        payload["_lineage"].update(
            {
                "price": {"evidence_ids": ["price"]},
                "currency": {"evidence_ids": ["currency"]},
                "materials": {"evidence_ids": ["materials"]},
            }
        )
    return SimpleNamespace(
        records=(_Record(payload),), verdict="success", data_integrity="clean"
    )


def test_loads_both_html_grounded_references_from_directory(tmp_path: Path) -> None:
    references = _references()
    root = tmp_path / "reference"
    root.mkdir()
    (root / quality_cases.EVAL_REFERENCE).write_text(
        json.dumps(references["evaluation"]), encoding="utf-8"
    )
    (root / quality_cases.DEFECT_REFERENCE).write_text(
        json.dumps(references["defects"]), encoding="utf-8"
    )

    assert quality_cases.load_artifact_quality_cases(root) == references


def test_validation_selects_latest_retry_and_distinguishes_zara_queries(
    tmp_path: Path,
) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)
    retry = _write_capture(
        tmp_path,
        run_id="2",
        result_id=100,
        url=references["evaluation"]["cases"][0]["url"],
    )
    expected_hash = hashlib.sha256((retry / "page.html").read_bytes()).hexdigest()
    references["evaluation"]["cases"][0]["capture_hashes"] = {
        "page.html": expected_hash
    }

    assert (
        quality_cases.validate_artifact_quality_cases(references, backend_root=tmp_path)
        == []
    )


def test_validation_prefers_matching_query_state_over_same_path_fallback(
    tmp_path: Path,
) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)
    first = references["evaluation"]["cases"][0]
    first["url"] = "https://shop1.example/products/acme-widget"
    _write_capture(
        tmp_path,
        run_id="2",
        result_id=100,
        url="https://shop1.example/products/acme-widget?color=blue",
    )
    queryless = _write_capture(
        tmp_path,
        run_id="1",
        result_id=101,
        url="http://shop1.example/products/acme-widget/details",
    )
    first["capture_hashes"] = {
        "page.html": hashlib.sha256((queryless / "page.html").read_bytes()).hexdigest()
    }

    assert (
        quality_cases.validate_artifact_quality_cases(references, backend_root=tmp_path)
        == []
    )


def test_validation_rejects_sibling_capture_with_only_generic_token_overlap(
    tmp_path: Path,
) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)
    references["evaluation"]["cases"][0]["url"] = (
        "https://shop1.example/products/acme-widget"
    )
    _write_capture(
        tmp_path,
        run_id="2",
        result_id=100,
        url="https://shop1.example/products/acme-jacket",
    )

    errors = quality_cases.validate_artifact_quality_cases(
        references, backend_root=tmp_path
    )

    assert errors == ["case 1 has no matching capture"]


def test_validation_accepts_capture_with_related_product_slug(tmp_path: Path) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)
    first = references["evaluation"]["cases"][0]
    first["url"] = "https://shop1.example/product/123/products/makeup/eyes/eye-shadow"
    related = _write_capture(
        tmp_path,
        run_id="2",
        result_id=100,
        url="https://shop1.example/products/small-eye-shadow?modal=region",
    )
    first["capture_hashes"] = {
        "page.html": hashlib.sha256((related / "page.html").read_bytes()).hexdigest()
    }

    assert (
        quality_cases.validate_artifact_quality_cases(references, backend_root=tmp_path)
        == []
    )


def test_validation_fails_missing_ambiguous_and_hash_mismatched_captures(
    tmp_path: Path,
) -> None:
    references = _references()
    assert (
        "captures found"
        in quality_cases.validate_artifact_quality_cases(
            references, backend_root=tmp_path
        )[0]
    )

    _write_all_captures(tmp_path, references)
    references["evaluation"]["cases"][0]["capture_hashes"] = {"page.html": "wrong"}
    assert (
        "hash mismatch"
        in quality_cases.validate_artifact_quality_cases(
            references, backend_root=tmp_path
        )[0]
    )

    references["evaluation"]["cases"][0].pop("capture_hashes")
    first_url = references["evaluation"]["cases"][0]["url"]
    _write_capture(tmp_path, run_id="2", result_id=200, url=first_url)
    _write_capture(tmp_path, run_id="02", result_id=200, url=first_url)
    assert (
        "ambiguous"
        in quality_cases.validate_artifact_quality_cases(
            references, backend_root=tmp_path
        )[0]
    )


def test_audit_supports_projection_constraints_forbidden_values_and_partitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)
    monkeypatch.setattr(quality_cases, "extract", _fake_result)

    report = quality_cases.audit_artifact_quality_cases(
        references,
        backend_root=tmp_path,
        partitions=("commercial_fields",),
    )

    first = report["cases"][0]
    assert first["run_id"] == 1
    assert first["asserted_fields"] == (
        "currency",
        "material",
        "price",
        "selected_fit",
        "size_options",
        "title",
    )
    assert first["failures"] == ()
    assert tuple(row["case_id"] for row in report["cases"]) == tuple(range(1, 83))
    assert report["selected_capture_hashes"]["1"]["page.html"]
    assert set(report["timing_ms"]) == {"mean", "p50", "p95"}

    references["evaluation"]["cases"][0]["forbidden"] = {"title": ["Product 1"]}
    failed = quality_cases.audit_artifact_quality_cases(
        references, backend_root=tmp_path, partitions=("commercial_fields",)
    )
    assert failed["failed_case_ids"] == (1,)
    assert "forbidden value" in failed["cases"][0]["failures"][0]


def test_audit_rejects_unknown_partition(tmp_path: Path) -> None:
    references = _references()
    _write_all_captures(tmp_path, references)

    with pytest.raises(ValueError, match="unknown defect partitions"):
        quality_cases.audit_artifact_quality_cases(
            references, backend_root=tmp_path, partitions=("unknown",)
        )


def test_audit_reports_fallback_reference_as_capture_limited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    references = _references()
    references["evaluation"]["cases"][81]["source"] = "fallback"
    _write_all_captures(tmp_path, references)
    monkeypatch.setattr(quality_cases, "extract", _fake_result)

    report = quality_cases.audit_artifact_quality_cases(
        references, backend_root=tmp_path
    )

    assert report["capture_limited_case_ids"] == (82,)
    assert report["cases"][81]["asserted_fields"] == ()
