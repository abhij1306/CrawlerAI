"""Unit tests for the per-(domain, surface) execution baseline (Slice 5)."""

from __future__ import annotations

import pytest

from app.services.config import audit_rules
from app.services.config import observability as obs_config
from app.services.observability import baseline as baseline_mod

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _tmp_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline_mod.settings, "artifacts_dir", tmp_path)
    return tmp_path


def _obs(**kwargs):
    base = {
        "completed_tiers": ["authoritative", "structured_data", "js_state", "dom"],
        "fields_present": ["price", "title", "image_url"],
        "engine": "patchright",
        "total_acquire_ms": 10000,
        "verdict": "success",
    }
    base.update(kwargs)
    return baseline_mod.build_observation(**base)


def _seed(domain="example.com", surface="ecommerce_detail", n=None):
    n = n or obs_config.BASELINE_MIN_SAMPLES
    for _ in range(n):
        baseline_mod.update_baseline(domain, surface, _obs())
    return baseline_mod.load_baseline(domain, surface)


def test_no_drift_until_min_samples():
    baseline_mod.update_baseline("example.com", "ecommerce_detail", _obs())
    baseline = baseline_mod.load_baseline("example.com", "ecommerce_detail")
    # only 1 sample, below BASELINE_MIN_SAMPLES => no drift flags
    flags = baseline_mod.compare_to_baseline(baseline, _obs(fields_present=[]))
    assert flags == []


def test_field_regression_flagged_after_baseline_established():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(
        baseline,
        _obs(fields_present=["title", "image_url"]),  # lost price
    )
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_FIELD_REGRESSION in codes
    field_flag = next(f for f in flags if f["code"] == audit_rules.FLAG_BASELINE_FIELD_REGRESSION)
    assert "price" in field_flag["evidence"]["lost_fields"]


def test_tier_regression_flagged():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(
        baseline,
        _obs(completed_tiers=["authoritative", "structured_data", "js_state"]),  # no dom
    )
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_TIER_REGRESSION in codes


def test_engine_change_flagged():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(baseline, _obs(engine="real_chrome"))
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_ENGINE_CHANGED in codes


def test_verdict_regression_flagged():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(baseline, _obs(verdict="empty"))
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_VERDICT_REGRESSION in codes


def test_timing_breach_flagged():
    baseline = _seed()  # avg ~10000ms
    flags = baseline_mod.compare_to_baseline(baseline, _obs(total_acquire_ms=60000))
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_TIMING_BREACH in codes


def test_minor_timing_variation_not_flagged():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(baseline, _obs(total_acquire_ms=11000))
    codes = {f["code"] for f in flags}
    assert audit_rules.FLAG_BASELINE_TIMING_BREACH not in codes


def test_stable_run_produces_no_drift():
    baseline = _seed()
    flags = baseline_mod.compare_to_baseline(baseline, _obs())
    assert flags == []


def test_baseline_scoped_by_domain_surface():
    _seed(domain="a.com", surface="ecommerce_detail")
    # different surface has no baseline yet
    assert baseline_mod.load_baseline("a.com", "ecommerce_listing") is None
    # different domain has no baseline yet
    assert baseline_mod.load_baseline("b.com", "ecommerce_detail") is None


def test_update_rolls_samples_and_intersects_fields():
    baseline_mod.update_baseline("x.com", "ecommerce_detail", _obs())
    baseline_mod.update_baseline(
        "x.com",
        "ecommerce_detail",
        _obs(fields_present=["price", "title"]),  # no image_url this time
    )
    baseline = baseline_mod.load_baseline("x.com", "ecommerce_detail")
    assert baseline["samples"] == 2
    # intersection drops image_url (not present in both)
    assert "image_url" not in baseline["fields"]
    assert "price" in baseline["fields"]
