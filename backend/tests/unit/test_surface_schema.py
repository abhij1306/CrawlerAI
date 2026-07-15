from __future__ import annotations

from app.extraction.surfaces import (
    SURFACE_SPECS,
    Surface,
    listing_schema,
    structured_type_selectors,
    surface_spec,
)


def test_every_spec_has_consistent_fact_sets() -> None:
    for surface, spec in SURFACE_SPECS.items():
        assert spec.required_facts, surface
        assert spec.required_facts <= spec.allowed_facts, surface
        assert spec.record_signal_facts <= spec.allowed_facts, surface
        assert spec.min_record_signals >= 1, surface
        for fact, _kind in spec.listing_structured_fact_kinds:
            assert fact in spec.allowed_facts, (surface, fact)
        for fact, _keys in spec.listing_network_fact_keys:
            assert fact in spec.allowed_facts, (surface, fact)


def test_listing_schema_returns_lens_for_many_surfaces() -> None:
    for surface in (Surface.ECOMMERCE_LISTING, Surface.JOB_LISTING):
        schema = listing_schema(surface)
        assert schema is not None, surface
        assert schema.title_fact.endswith(".title")
        assert schema.url_fact.endswith(".url")
        # bindable_facts always leads with the title fact.
        assert schema.bindable_facts[0] == schema.title_fact
        # entity_type_for splits on the dot.
        assert schema.entity_type_for("job.title") == "job"


def test_listing_schema_returns_none_for_detail_surfaces() -> None:
    assert listing_schema(Surface.ECOMMERCE_DETAIL) is None
    assert listing_schema(Surface.JOB_DETAIL) is None


def test_jobs_allow_off_host_records_commerce_does_not() -> None:
    assert listing_schema(Surface.JOB_LISTING).off_host_records_allowed is True
    assert listing_schema(Surface.ECOMMERCE_LISTING).off_host_records_allowed is False
    assert surface_spec(Surface.JOB_DETAIL).off_host_records_allowed is True
    assert surface_spec(Surface.ECOMMERCE_DETAIL).off_host_records_allowed is False


def test_job_listing_carries_network_identity_keys() -> None:
    schema = listing_schema(Surface.JOB_LISTING)
    assert "jobId" in schema.network_identity_keys
    # commerce listing has no identity keys (uses url grounding directly).
    assert listing_schema(Surface.ECOMMERCE_LISTING).network_identity_keys == ()


def test_structured_type_selectors_exclude_itemlist() -> None:
    selectors = structured_type_selectors(Surface.JOB_LISTING)
    assert any("JobPosting" in sel for sel in selectors)
    assert all("ItemList" not in sel for sel in selectors)
