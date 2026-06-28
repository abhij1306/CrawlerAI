from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from harness.artifact_quality_cases import (
    _acquisition_blocked,
    _acquisition_status_code,
    _deep_merge_mappings,
    _string_sequence,
    audit_artifact_quality_cases,
    load_artifact_quality_cases,
    validate_artifact_quality_cases,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "extraction"
    / "latest_commerce_artifact_integrity_20260627.json"
)
BACKEND_ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _fixture_artifacts_available(manifest: dict[str, object]) -> bool:
    root = BACKEND_ROOT / str(manifest.get("artifact_root") or "")
    cases = manifest.get("cases")
    return isinstance(cases, list) and all(
        (root / str(case.get("url_result_id") or "") / str(name)).is_file()
        for case in cases
        if isinstance(case, dict)
        for name in case.get("artifact_files") or []
    )


def _fallback_artifact_cases(root: Path) -> tuple[dict[str, object], Path]:
    source_url = "https://shop.test/products/plush-bath-towels"
    result_root = root / "results" / "1"
    result_root.mkdir(parents=True)
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Plush Turkish Cotton Bath Towels Set of 2",
          "brand": {"@type": "Brand", "name": "Brooklinen"},
          "description": "A plush set of two Turkish cotton bath towels.",
          "sku": "BATH-SET",
          "url": "https://shop.test/products/plush-bath-towels",
          "image": "https://shop.test/images/plush-bath-towels.jpg",
          "offers": {
            "@type": "Offer",
            "price": "79",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "BATH-WHITE",
              "color": "White",
              "size": "Set of 2",
              "material": "Cotton"
            },
            {
              "@type": "Product",
              "sku": "BATH-SMOKE",
              "color": "Smoke",
              "size": "Set of 2",
              "material": "Cotton"
            }
          ]
        }
        </script>
      </head>
      <body><main><h1>Plush Turkish Cotton Bath Towels Set of 2</h1></main></body>
    </html>
    """
    summary = {
        "acquisition": {
            "final_url": source_url,
            "method": "httpx",
            "status_code": 200,
            "blocked": False,
            "network_payloads": [],
            "browser_diagnostics": {},
            "acquisition_diagnostics": {},
        }
    }
    (result_root / "page.html").write_text(html, encoding="utf-8")
    (result_root / "records.json").write_text("[]", encoding="utf-8")
    (result_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    manifest: dict[str, object] = {
        "version": 1,
        "artifact_root": "results",
        "cases": [
            {
                "case_id": "brooklinen-network-variant-pollution",
                "url_result_id": 1,
                "source_url": source_url,
                "expected_field_states": {
                    "title": "captured_and_resolved",
                    "brand": "captured_and_resolved",
                    "variants": "captured_and_resolved",
                },
                "expected_invariants": {
                    "selected_product_title": (
                        "Plush Turkish Cotton Bath Towels Set of 2"
                    ),
                    "forbidden_variant_materials": ["Wool/Cotton"],
                },
                "artifact_files": ["records.json", "summary.json", "page.html"],
            }
        ],
    }
    return manifest, root


@pytest.fixture(scope="module")
def artifact_cases(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, object], Path]:
    return _fallback_artifact_cases(tmp_path_factory.mktemp("artifact-replay"))


def test_latest_commerce_artifact_manifest_is_valid_and_offline(
    artifact_cases: tuple[dict[str, object], Path],
) -> None:
    source_manifest = load_artifact_quality_cases(FIXTURE)
    source_cases = source_manifest.get("cases")
    assert source_manifest.get("version") == 1
    assert isinstance(source_cases, list) and source_cases
    case_ids = [str(case.get("case_id") or "") for case in source_cases]
    assert all(case_ids)
    assert len(case_ids) == len(set(case_ids))
    if _fixture_artifacts_available(source_manifest):
        assert (
            validate_artifact_quality_cases(
                source_manifest,
                backend_root=BACKEND_ROOT,
            )
            == []
        )

    manifest, backend_root = artifact_cases
    assert validate_artifact_quality_cases(manifest, backend_root=backend_root) == []


def test_latest_commerce_artifacts_are_integrity_clean() -> None:
    manifest = load_artifact_quality_cases(FIXTURE)
    if not _fixture_artifacts_available(manifest):
        pytest.skip("latest local crawl artifacts are unavailable")

    report = audit_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)

    assert report["quality_clean"] is True
    assert report["unresolved_issue_ids"] == ()
    assert {case["classification"] for case in report["cases"]} <= {
        "artifact_consistent",
        "source_unavailable",
    }


def test_brooklinen_case_has_no_duplicate_or_feed_variants() -> None:
    manifest = load_artifact_quality_cases(FIXTURE)
    if not _fixture_artifacts_available(manifest):
        pytest.skip("latest local crawl artifacts are unavailable")

    report = audit_artifact_quality_cases(manifest, backend_root=BACKEND_ROOT)
    case = next(
        row
        for row in report["cases"]
        if row["case_id"] == "brooklinen-network-variant-pollution"
    )

    assert case["field_states"]["variants"] == "captured_and_resolved"
    assert case["signals"]["duplicate_variant_ids"] == ()
    assert case["signals"]["forbidden_variant_materials"] == ()
    assert case["invariant_failures"] == ()


def test_artifact_quality_gate_fails_without_issue_id_metadata(
    artifact_cases: tuple[dict[str, object], Path],
) -> None:
    source_manifest, backend_root = artifact_cases
    manifest = deepcopy(source_manifest)
    case = manifest["cases"][0]
    case["expected_invariants"] = {"expected_brand": "Not Brooklinen"}

    report = audit_artifact_quality_cases(manifest, backend_root=backend_root)

    assert report["quality_clean"] is False
    assert report["unresolved_issue_ids"] == ()
    assert report["cases"][0]["classification"] == "integrity_failure"


def test_artifact_quality_gate_enforces_required_locale_evidence(
    artifact_cases: tuple[dict[str, object], Path],
) -> None:
    source_manifest, backend_root = artifact_cases
    manifest = deepcopy(source_manifest)
    case = manifest["cases"][0]
    case["expected_invariants"] = {
        "expected_currency": "EUR",
        "required_description_fragments": ["texte français"],
    }

    report = audit_artifact_quality_cases(manifest, backend_root=backend_root)

    assert report["quality_clean"] is False
    assert set(report["cases"][0]["invariant_failures"]) == {
        "currency_matches",
        "required_description_fragments_missing",
    }


def test_artifact_replay_derives_blocked_from_browser_evidence() -> None:
    acquisition = {
        "blocked": False,
        "method": "browser",
        "browser_diagnostics": {"browser_outcome": "challenge_page"},
    }

    assert _acquisition_blocked(acquisition) is True


def test_artifact_replay_status_falls_back_to_earlier_http_attempt() -> None:
    acquisition = {
        "acquisition_diagnostics": {
            "result": {
                "selected_attempt_id": "browser-1",
                "attempts": [
                    {
                        "attempt_id": "http-1",
                        "status_code": 503,
                        "diagnostics": {"transport": "httpx"},
                    },
                    {
                        "attempt_id": "browser-1",
                        "status_code": None,
                        "diagnostics": {"transport": "browser"},
                    },
                ],
            }
        }
    }

    assert _acquisition_status_code(acquisition) == 503


def test_artifact_replay_status_falls_back_to_later_http_attempt() -> None:
    acquisition = {
        "acquisition_diagnostics": {
            "result": {
                "selected_attempt_id": "browser-1",
                "attempts": [
                    {
                        "attempt_id": "browser-1",
                        "status_code": None,
                        "diagnostics": {"transport": "browser"},
                    },
                    {
                        "attempt_id": "http-1",
                        "status_code": 503,
                        "diagnostics": {"transport": "httpx"},
                    },
                ],
            }
        }
    }

    assert _acquisition_status_code(acquisition) == 503


def test_artifact_acquisition_merge_preserves_nested_diagnostics() -> None:
    merged = _deep_merge_mappings(
        {
            "browser_diagnostics": {"browser_outcome": "usable_content"},
            "acquisition_diagnostics": {"result": {"plan_id": "plan-1"}},
        },
        {
            "browser_diagnostics": {"browser_attempted": True},
            "acquisition_diagnostics": {"result": {"selected_attempt_id": "browser-1"}},
        },
    )

    assert merged["browser_diagnostics"] == {
        "browser_outcome": "usable_content",
        "browser_attempted": True,
    }
    assert merged["acquisition_diagnostics"]["result"] == {
        "plan_id": "plan-1",
        "selected_attempt_id": "browser-1",
    }


def test_artifact_string_sets_are_materialized_deterministically() -> None:
    assert _string_sequence({"zeta", "alpha"}) == ("alpha", "zeta")


def test_artifact_replay_status_prefers_selected_integer_status() -> None:
    acquisition = {
        "acquisition_diagnostics": {
            "result": {
                "selected_attempt_id": "browser-1",
                "attempts": [
                    {
                        "attempt_id": "http-1",
                        "status_code": 503,
                        "diagnostics": {"transport": "httpx"},
                    },
                    {
                        "attempt_id": "browser-1",
                        "status_code": 200,
                        "diagnostics": {"transport": "browser"},
                    },
                ],
            }
        }
    }

    assert _acquisition_status_code(acquisition) == 200
