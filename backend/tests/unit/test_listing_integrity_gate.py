"""Unit tests for evaluate_listing_integrity in listing_integrity_gate.

Covers all decision paths:
- product_grid / supported_set (happy path)
- promo_only_cluster / below_min_records
- promo_only_cluster / cohort_heterogeneous
- promo_only_cluster / all_sibling_category_urls
- promo_only_cluster / no_support_signals
- Edge cases: empty records, single record, all same URL shape
"""

from __future__ import annotations

import pytest

from unittest.mock import patch

from app.services.extract.listing_integrity_gate import (
    IntegrityDecision,
    ensure_frozenset,
    evaluate_listing_integrity,
)


def _product_record(idx: int, *, price: str = "$10", image: str = "img.jpg") -> dict:
    """Build a product-like record with detail-like URL and support signals."""
    return {
        "title": f"Product {idx}",
        "url": f"https://example.com/products/product-{idx}-SKU{idx:04d}",
        "price": price,
        "image_url": image,
    }


def _category_record(idx: int) -> dict:
    """Build a sibling-category record (structural URL, no support signals)."""
    return {
        "title": f"Category {idx}",
        "url": f"https://example.com/category/cat-{idx}",
    }


@pytest.mark.unit
def test_ensure_frozenset_uses_mapping_values() -> None:
    assert ensure_frozenset({"primary": "price", "secondary": "image_url"}) == frozenset(
        {"price", "image_url"}
    )


class TestEvaluateListingIntegrityProductGrid:
    """Tests for the product_grid / supported_set outcome."""

    @pytest.mark.unit
    def test_supported_set_with_detail_markers_and_support_signals(self):
        records = [_product_record(i) for i in range(5)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert decision.outcome == "product_grid"
        assert decision.reason == "supported_set"
        assert decision.metrics["record_count"] == 5
        assert decision.metrics["support_signal_count"] >= 1

    @pytest.mark.unit
    def test_single_record_with_support_signals_passes(self):
        records = [_product_record(1)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert decision.outcome == "product_grid"
        assert decision.reason == "supported_set"

    @pytest.mark.unit
    def test_empty_records_returns_product_grid(self):
        """Empty set is not rejected — it's a no-op pass-through."""
        decision = evaluate_listing_integrity(
            [], page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        # Empty records: cohort_homogeneity=1.0, sibling_count=0,
        # detail_marker_count=0, support_signal_count=0.
        # Rule 4 requires sibling_category_count > 0 to fire, so it passes.
        assert decision.outcome == "product_grid"
        assert decision.reason == "supported_set"

    @pytest.mark.unit
    def test_records_with_high_homogeneity_pass(self):
        """All records share the same URL shape → high homogeneity → pass."""
        records = [_product_record(i) for i in range(10)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert decision.outcome == "product_grid"
        assert decision.metrics["cohort_homogeneity_ratio"] >= 0.6


class TestEvaluateListingIntegrityPromoCluster:
    """Tests for promo_only_cluster outcomes."""

    @pytest.mark.unit
    def test_below_min_records_with_all_sibling_category(self):
        """Below min_records AND all sibling-category AND no support → promo_only_cluster."""
        # Use category URLs that share a category path prefix with the page URL
        records = [
            {"title": "Category A", "url": "https://example.com/c/promo-a"},
        ]
        with patch(
            "app.services.extract.listing_integrity_gate.crawler_runtime_settings"
        ) as mock_settings:
            mock_settings.listing_integrity_min_records = 3
            mock_settings.listing_cohort_homogeneity_min_ratio = 0.6
            decision = evaluate_listing_integrity(
                records,
                page_url="https://example.com/c/main-category",
                surface="ecommerce_listing",
            )
        assert decision.outcome == "promo_only_cluster"
        assert decision.reason == "below_min_records"

    @pytest.mark.unit
    def test_below_min_records_with_support_signals_passes(self):
        """Below min_records but has support signals → product_grid (not rejected)."""
        records = [_product_record(1)]
        with patch(
            "app.services.extract.listing_integrity_gate.crawler_runtime_settings"
        ) as mock_settings:
            mock_settings.listing_integrity_min_records = 5
            mock_settings.listing_cohort_homogeneity_min_ratio = 0.6
            decision = evaluate_listing_integrity(
                records,
                page_url="https://example.com/shop",
                surface="ecommerce_listing",
            )
        assert decision.outcome == "product_grid"
        assert decision.reason == "supported_set"

    @pytest.mark.unit
    def test_cohort_heterogeneous(self):
        """Low cohort homogeneity → promo_only_cluster / cohort_heterogeneous."""
        # Mix very different URL shapes with no support signals (no price,
        # image, rating, etc.) so the support-signal override does not apply.
        records = [
            {"title": "A", "url": "https://example.com/a"},
            {"title": "B", "url": "https://example.com/cat/sub/deep/b-123"},
            {"title": "C", "url": "https://other.com/c"},
            {"title": "D", "url": "https://example.com/products/d-SKU0001"},
            {"title": "E", "url": "https://example.com/shop/category/e"},
        ]
        with patch(
            "app.services.extract.listing_integrity_gate.crawler_runtime_settings"
        ) as mock_settings:
            mock_settings.listing_integrity_min_records = 2
            mock_settings.listing_cohort_homogeneity_min_ratio = 0.9
            decision = evaluate_listing_integrity(
                records,
                page_url="https://example.com/shop",
                surface="ecommerce_listing",
            )
        assert decision.outcome == "promo_only_cluster"
        assert decision.reason == "cohort_heterogeneous"
        assert decision.metrics["cohort_homogeneity_ratio"] < 0.9

    @pytest.mark.unit
    def test_all_sibling_category_urls(self):
        """All records are sibling-category URLs → promo_only_cluster."""
        # Both page and records share /c/ category prefix → structural
        records = [
            {"title": f"Category {i}", "url": f"https://example.com/c/cat-{i}"}
            for i in range(5)
        ]
        decision = evaluate_listing_integrity(
            records,
            page_url="https://example.com/c/parent-category",
            surface="ecommerce_listing",
        )
        assert decision.outcome == "promo_only_cluster"
        assert decision.reason == "all_sibling_category_urls"

    @pytest.mark.unit
    def test_no_support_signals_with_sibling_category_present(self):
        """No detail markers, no support signals, but sibling category present → promo_only_cluster."""
        # Records with sibling-category URLs (share /c/ prefix with page)
        records = [
            {"title": "Promo A", "url": "https://example.com/c/promo-a"},
            {"title": "Promo B", "url": "https://example.com/c/promo-b"},
            {"title": "Promo C", "url": "https://example.com/c/promo-c"},
        ]
        decision = evaluate_listing_integrity(
            records,
            page_url="https://example.com/c/main",
            surface="ecommerce_listing",
        )
        # These are structural/sibling URLs → caught by all_sibling_category_urls
        assert decision.outcome == "promo_only_cluster"


class TestEvaluateListingIntegrityMetrics:
    """Tests that metrics are always populated regardless of outcome."""

    @pytest.mark.unit
    def test_metrics_always_present(self):
        records = [_product_record(i) for i in range(3)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert "record_count" in decision.metrics
        assert "cohort_homogeneity_ratio" in decision.metrics
        assert "dominant_signature_count" in decision.metrics
        assert "sibling_category_count" in decision.metrics
        assert "support_signal_count" in decision.metrics
        assert "detail_marker_count" in decision.metrics

    @pytest.mark.unit
    def test_metrics_record_count_matches_input(self):
        records = [_product_record(i) for i in range(7)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert decision.metrics["record_count"] == 7

    @pytest.mark.unit
    def test_decision_is_frozen_dataclass(self):
        records = [_product_record(1)]
        decision = evaluate_listing_integrity(
            records, page_url="https://example.com/shop", surface="ecommerce_listing"
        )
        assert isinstance(decision, IntegrityDecision)
        # Frozen — cannot mutate
        try:
            decision.outcome = "hacked"  # type: ignore[misc]
            assert False, "Should have raised"
        except Exception:
            pass


class TestEvaluateListingIntegrityJobSurface:
    """Tests for job_listing surface support fields."""

    @pytest.mark.unit
    def test_job_listing_with_company_field_passes(self):
        records = [
            {
                "title": "Software Engineer",
                "url": "https://jobs.example.com/jobs/12345-software-engineer",
                "company": "Acme Corp",
            }
            for _ in range(5)
        ]
        decision = evaluate_listing_integrity(
            records, page_url="https://jobs.example.com/search", surface="job_listing"
        )
        assert decision.outcome == "product_grid"
        assert decision.metrics["support_signal_count"] >= 1
