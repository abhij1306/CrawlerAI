"""Unit tests for the from-scratch run auditor (Slice 4).

Validates the deterministic symptom -> INVARIANT -> owner flag mapping using
lightweight stand-in run/record objects and a temp artifacts dir for the
trace/browser artifact reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.config import audit_rules
from app.services.config import observability as obs_config
from app.services.observability import baseline as baseline_mod
from app.services.observability import run_audit

pytestmark = pytest.mark.unit


def _run(*, surface: str, verdict: str, requested_fields=None, run_id: int = 1):
    return SimpleNamespace(
        id=run_id,
        surface=surface,
        result_summary={"extraction_verdict": verdict},
        requested_fields=list(requested_fields or []),
    )


def _record(*, url: str = "https://e.com/p/x", data=None, source_trace=None):
    return SimpleNamespace(
        source_url=url,
        data=dict(data or {}),
        source_trace=dict(source_trace or {}),
    )


def _flag_with_code(flags, code: str):
    for flag in flags:
        if flag["code"] == code:
            return flag
    raise AssertionError(f"Flag not found: {code}")


def test_listing_single_metadata_record_flagged():
    run = _run(surface="ecommerce_listing", verdict="success")
    record = _record(data={"title": "Some Page", "url": "https://e.com/c/shoes"})
    flags = run_audit.build_run_flags(run, [record])
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_LISTING_SINGLE_METADATA_RECORD in codes
    flag = _flag_with_code(flags, audit_rules.FLAG_LISTING_SINGLE_METADATA_RECORD)
    assert flag["owner"] == audit_rules.OWNER_LISTING_EXTRACTOR
    assert "Rule 7" in flag["invariant"]


def test_listing_single_rich_metadata_record_flagged():
    run = _run(surface="ecommerce_listing", verdict="success")
    record = _record(
        data={
            "title": "Some Page",
            "description": "Category page",
            "canonical_url": "https://e.com/c/shoes",
            "image_url": "https://e.com/og.jpg",
            "site_name": "Example",
        }
    )

    flags = run_audit.build_run_flags(run, [record])
    codes = {f["code"] for f in flags}

    assert audit_rules.FLAG_LISTING_SINGLE_METADATA_RECORD in codes
    flag = _flag_with_code(flags, audit_rules.FLAG_LISTING_SINGLE_METADATA_RECORD)
    assert flag["owner"] == audit_rules.OWNER_LISTING_EXTRACTOR
    assert "Rule 7" in flag["invariant"]


def test_listing_with_real_rows_not_flagged():
    run = _run(surface="ecommerce_listing", verdict="success")
    records = [
        _record(data={"title": "A", "url": "https://e.com/p/a", "price": "1.00"}),
        _record(data={"title": "B", "url": "https://e.com/p/b", "price": "2.00"}),
    ]
    flags = run_audit.build_run_flags(run, records)
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_LISTING_SINGLE_METADATA_RECORD not in codes


def test_high_value_field_missing_flagged():
    run = _run(
        surface="ecommerce_detail", verdict="partial", requested_fields=["price"]
    )
    record = _record(data={"title": "Widget", "image_url": "https://e.com/i.jpg"})
    flags = run_audit.build_run_flags(run, [record])
    missing = [
        f for f in flags if f["code"] == audit_rules.FLAG_HIGH_VALUE_FIELD_MISSING
    ]
    assert missing
    assert "price" in missing[0]["evidence"]["missing_fields"]


def test_high_value_field_missing_suppressed_when_diagnosed():
    run = _run(
        surface="ecommerce_detail", verdict="partial", requested_fields=["price"]
    )
    record = _record(
        data={"title": "Widget", "image_url": "https://e.com/i.jpg"},
        source_trace={"field_discovery_missing": ["price"]},
    )
    flags = run_audit.build_run_flags(run, [record])
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_HIGH_VALUE_FIELD_MISSING not in codes


def test_dom_skipped_with_variant_cues_flagged():
    run = _run(
        surface="ecommerce_detail", verdict="success", requested_fields=["variants"]
    )
    record = _record(
        data={
            "title": "Sneaker",
            "price": "99.00",
            "image_url": "https://e.com/i.jpg",
            "available_sizes": ["8", "9", "10"],  # variant cue
        },
        source_trace={
            "extraction": {
                "dom_skip": {
                    "dom_skipped": True,
                    "confidence": 0.82,
                    "threshold": 0.7,
                    "reason": "confidence_cleared_no_dom_completion_needed",
                }
            }
        },
    )
    flags = run_audit.build_run_flags(run, [record])
    dom_flags = [
        f for f in flags if f["code"] == audit_rules.FLAG_DOM_SKIPPED_WITH_VARIANT_CUES
    ]
    assert dom_flags
    assert dom_flags[0]["owner"] == audit_rules.OWNER_DETAIL_TIERS
    assert dom_flags[0]["evidence"]["confidence"] == pytest.approx(0.82)


def test_dom_skip_not_flagged_when_variants_present():
    run = _run(
        surface="ecommerce_detail", verdict="success", requested_fields=["variants"]
    )
    record = _record(
        data={
            "title": "Sneaker",
            "price": "99.00",
            "image_url": "https://e.com/i.jpg",
            "variants": [{"size": "8"}],
            "available_sizes": ["8"],
        },
        source_trace={"extraction": {"dom_skip": {"dom_skipped": True}}},
    )
    flags = run_audit.build_run_flags(run, [record])
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_DOM_SKIPPED_WITH_VARIANT_CUES not in codes


def test_usable_content_but_blocked_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    run_id = 42
    pages = tmp_path / "runs" / str(run_id) / "pages"
    pages.mkdir(parents=True)
    (pages / "abc.browser.json").write_text(
        json.dumps(
            {
                "browser_outcome": "usable_content",
                "final_url": "https://e.com/p/x",
                "host_outcome": {"result": "blocked", "blocked": True},
            }
        ),
        encoding="utf-8",
    )
    run = _run(surface="ecommerce_detail", verdict="blocked", run_id=run_id)
    flags = run_audit.build_run_flags(run, [])
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_USABLE_CONTENT_BUT_BLOCKED in codes


def test_browser_artifact_challenge_shell_flag_uses_probe_url(tmp_path, monkeypatch):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    run_id = 44
    pages = tmp_path / "runs" / str(run_id) / "pages"
    pages.mkdir(parents=True)
    (pages / "abc.browser.json").write_text(
        json.dumps(
            {
                "browser_outcome": "low_content_shell",
                "failure_reason": "challenge_shell",
                "readiness_probes": [{"url": "https://yeti.example/p/1"}],
                "challenge_provider_hits": ["px-captcha"],
            }
        ),
        encoding="utf-8",
    )
    run = _run(surface="ecommerce_detail", verdict="blocked", run_id=run_id)

    flags = run_audit.build_run_flags(run, [])
    flag = _flag_with_code(flags, audit_rules.FLAG_ACQUISITION_CHALLENGE_BLOCKED)

    assert flag["url"] == "https://yeti.example/p/1"


def test_trace_rejection_flags_challenge_shell_and_updates_each_domain_baseline(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    pages = tmp_path / "runs" / "51" / "pages"
    pages.mkdir(parents=True)
    (pages / "a.trace.json").write_text(
        json.dumps(
            {
                "run_id": 51,
                "url": "https://alpha.example/p/1",
                "surface": "ecommerce_detail",
                "verdict": "success",
                "acquire_timeline": [
                    {
                        "kind": obs_config.ACQUIRE_EVENT_HTTP_FETCH,
                        "sequence": 1,
                        "detail": {"method": "curl_cffi", "status_code": 200},
                    }
                ],
                "extraction": {"completed_tiers": ["structured_data"]},
            }
        ),
        encoding="utf-8",
    )
    (pages / "b.trace.json").write_text(
        json.dumps(
            {
                "run_id": 51,
                "url": "https://beta.example/p/2",
                "surface": "ecommerce_detail",
                "verdict": "blocked",
                "acquire_timeline": [],
                "extraction": {
                    "completed_tiers": [],
                    "rejection_reason": "challenge_shell",
                },
            }
        ),
        encoding="utf-8",
    )
    run = _run(surface="ecommerce_detail", verdict="partial", run_id=51)
    record = _record(
        url="https://alpha.example/p/1",
        data={
            "title": "Alpha",
            "price": "10.00",
            "image_url": "https://alpha.example/i.jpg",
        },
    )

    flags = run_audit.build_run_flags(run, [record], update_baselines=True)
    codes = {f["code"] for f in flags}

    assert audit_rules.FLAG_ACQUISITION_CHALLENGE_BLOCKED in codes
    assert (
        baseline_mod.load_baseline("alpha.example", "ecommerce_detail")["samples"] == 1
    )
    assert (
        baseline_mod.load_baseline("beta.example", "ecommerce_detail")["samples"] == 1
    )


def test_trace_flags_variant_candidate_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    pages = tmp_path / "runs" / "52" / "pages"
    pages.mkdir(parents=True)
    (pages / "a.trace.json").write_text(
        json.dumps(
            {
                "run_id": 52,
                "url": "https://shop.example/p/1",
                "surface": "ecommerce_detail",
                "verdict": "success",
                "acquire_timeline": [],
                "extraction": {
                    "completed_tiers": ["structured_data", "dom"],
                    "field_provenance": [
                        {
                            "field": "variants",
                            "winning_source": "embedded_json",
                            "present": False,
                            "value_shape": "missing",
                            "note": "candidate_source_without_public_value",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    run = _run(surface="ecommerce_detail", verdict="success", run_id=52)

    flags = run_audit.build_run_flags(run, [])
    flag = _flag_with_code(flags, audit_rules.FLAG_VARIANT_CANDIDATE_DROPPED)

    assert flag["owner"] == audit_rules.OWNER_RECORD_ASSEMBLY
    assert flag["evidence"]["winning_source"] == "embedded_json"


def test_clean_run_produces_no_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    run = _run(
        surface="ecommerce_detail", verdict="success", requested_fields=["price"]
    )
    record = _record(
        data={
            "title": "Widget",
            "price": "10.00",
            "image_url": "https://e.com/i.jpg",
            "variants": [{"size": "M"}],
        }
    )
    flags = run_audit.build_run_flags(run, [record])
    assert flags == []


def test_write_flags_creates_audit_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(run_audit.settings, "artifacts_dir", tmp_path)
    flags = [
        {"code": "x", "severity": "high"},
        {"code": "y", "severity": "low"},
    ]
    path = run_audit._write_flags(99, flags)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["run_id"] == 99
    assert payload["flag_count"] == 2
    assert payload["severity_counts"] == {"high": 1, "low": 1}
    assert path.endswith(obs_config.FLAGS_FILENAME)
