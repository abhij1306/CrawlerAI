from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ucp_audit import UCPAuditPageResult, UCPAuditReport
from app.services.config.ucp_audit import (
    D_UCP1_ID,
    D_UCP2_ID,
    D_UCP3_ID,
    D_UCP4_ID,
    D_UCP5_ID,
    D_UCP6_ID,
    D_UCP7_ID,
    FINDING_DIMENSION_NOT_EVALUATED,
    UCP_AUDIT_JOB_STATUS_COMPLETE,
    UCP_AUDIT_JOB_STATUS_QUEUED,
)
from app.services.ucp_audit.service import (
    _best_agent_delta_url,
    build_ucp_report_for_domain,
    build_ucp_audit_job_payload,
    create_ucp_audit_job,
    get_ucp_audit_job,
    list_ucp_audit_jobs,
    run_job,
)
from app.services.ucp_audit.types import (
    AgentViewDelta,
    UCPComplianceReport,
    UCPDimensionScore,
    UCPManifestResult,
    UCPSchemaScore,
)


def _sample_report(audit_id: str = "audit-1") -> UCPComplianceReport:
    return UCPComplianceReport(
        domain="example.com",
        audit_id=audit_id,
        overall_score=82,
        dimension_scores=[
            UCPDimensionScore(
                dimension_id=D_UCP1_ID,
                score=100,
                status="pass",
                findings=[],
                weight=1.0,
            )
        ],
        all_findings=[],
        d_ucp1_gate_applied=False,
        agent_view_samples=[],
    )


@pytest.mark.asyncio
async def test_ucp_audit_job_creates_queued_row(
    db_session: AsyncSession,
    test_user,
) -> None:
    job = await create_ucp_audit_job(
        db_session,
        user=test_user,
        payload={
            "domain": "https://example.com",
            "options": {"sample_size": 3, "include_agent_delta": False},
        },
    )

    assert job.status == UCP_AUDIT_JOB_STATUS_QUEUED
    assert job.domain == "example.com"
    assert job.options["sample_size"] == 3
    assert job.summary["page_result_count"] == 0


@pytest.mark.asyncio
async def test_ucp_audit_run_job_persists_report_and_page_result(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_report(domain: str, audit_id: str, options: dict[str, object]):
        assert domain == "example.com"
        assert options["sample_size"] == 2
        return _sample_report(audit_id=audit_id)

    monkeypatch.setattr(
        "app.services.ucp_audit.service.build_ucp_report_for_domain",
        fake_report,
    )
    job = await create_ucp_audit_job(
        db_session,
        user=test_user,
        payload={"domain": "example.com", "options": {"sample_size": 2}},
    )

    await run_job(db_session, job)

    report = (
        await db_session.scalars(
            select(UCPAuditReport).where(UCPAuditReport.job_id == job.id)
        )
    ).one()
    page_result = (
        await db_session.scalars(
            select(UCPAuditPageResult).where(UCPAuditPageResult.job_id == job.id)
        )
    ).one()

    assert job.status == UCP_AUDIT_JOB_STATUS_COMPLETE
    assert job.summary["overall_score"] == 82
    assert report.overall_score == 82
    assert report.report_json["domain"] == "example.com"
    assert page_result.url == "https://example.com"


@pytest.mark.asyncio
async def test_ucp_audit_job_payload_serializes(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_report(domain: str, audit_id: str, options: dict[str, object]):
        del domain, options
        return _sample_report(audit_id=audit_id)

    monkeypatch.setattr(
        "app.services.ucp_audit.service.build_ucp_report_for_domain",
        fake_report,
    )
    job = await create_ucp_audit_job(
        db_session,
        user=test_user,
        payload={"domain": "example.com"},
    )
    await run_job(db_session, job)

    jobs = await list_ucp_audit_jobs(db_session, user=test_user)
    loaded = await get_ucp_audit_job(db_session, user=test_user, job_id=job.id)
    payload = await build_ucp_audit_job_payload(db_session, job=loaded)

    assert [row.id for row in jobs] == [job.id]
    assert payload["job"].id == job.id
    assert payload["report"].overall_score == 82
    assert len(payload["page_results"]) == 1


@pytest.mark.asyncio
async def test_ucp_report_evaluates_sampled_product_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_url = "https://example.com/products/widget"
    product_html = """
    <script type="application/ld+json">
    {
      "@type": "Product",
      "name": "Widget",
      "sku": "W-1",
      "brand": "Example",
      "description": "Strong widget",
      "image": "https://example.com/widget.jpg",
      "category": "Beauty > Nails > Press Ons",
      "additionalProperty": [
        {"name": "color", "value": "Red"},
        {"name": "size", "value": "M"},
        {"name": "material", "value": "Gel"},
        {"name": "brand", "value": "Example"},
        {"name": "gtin", "value": "123"}
      ],
      "offers": {
        "price": "10.00",
        "availability": "https://schema.org/InStock",
        "priceCurrency": "USD",
        "shippingDetails": {"shippingRate": "0"}
      }
    }
    </script>
    """

    async def fake_discover(domain: str) -> UCPManifestResult:
        del domain
        return UCPManifestResult(
            manifest_found=True,
            capabilities_declared=["dev.ucp.shopping"],
            missing_required_capabilities=[],
            manifest_valid=True,
            raw_manifest={},
        )

    async def fake_fetch_page(url: str, **kwargs):
        del kwargs

        class DummyPage:
            status_code = 200
            final_url = url
            content_type = "text/html"
            html = product_html

        if str(url).endswith("/sitemap.xml"):
            DummyPage.content_type = "application/xml"
            DummyPage.html = (
                "<?xml version='1.0'?><urlset>"
                f"<url><loc>{product_url}</loc></url>"
                "</urlset>"
            )
        return DummyPage()

    def fake_extract_records(*args, **kwargs):
        del args, kwargs
        return [
            {
                "variants": [
                    {
                        "price": "10.00",
                        "currency": "USD",
                        "sku": "W-RED",
                        "availability": "in_stock",
                    },
                    {
                        "price": "11.00",
                        "currency": "USD",
                        "sku": "W-BLUE",
                        "availability": "in_stock",
                    },
                ]
            }
        ]

    async def fake_agent_delta(url: str) -> AgentViewDelta:
        return AgentViewDelta(
            url=url,
            agent_extracted={"name": "Widget", "price": "10.00"},
            human_visible={"name": "Widget", "price": "10.00"},
            fidelity_score=1.0,
        )

    monkeypatch.setattr(
        "app.services.ucp_audit.service.discover_ucp_manifest",
        fake_discover,
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.service._fetch_audit_page",
        fake_fetch_page,
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.service.extract_records",
        fake_extract_records,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.ucp_audit.service.build_agent_view_delta",
        fake_agent_delta,
        raising=False,
    )

    report = await build_ucp_report_for_domain(
        "example.com",
        "audit-1",
        {"sample_size": 1, "include_agent_delta": True},
    )

    by_dimension = {item.dimension_id: item for item in report.dimension_scores}

    assert set(by_dimension) == {
        D_UCP1_ID,
        D_UCP2_ID,
        D_UCP3_ID,
        D_UCP4_ID,
        D_UCP5_ID,
        D_UCP6_ID,
        D_UCP7_ID,
    }
    assert all(
        finding.code != FINDING_DIMENSION_NOT_EVALUATED
        for finding in report.all_findings
    )
    assert by_dimension[D_UCP2_ID].score > 0
    assert by_dimension[D_UCP3_ID].score > 0
    assert by_dimension[D_UCP4_ID].score > 0
    assert by_dimension[D_UCP5_ID].score > 0
    assert by_dimension[D_UCP6_ID].score > 0
    assert by_dimension[D_UCP7_ID].score == 100
    assert report.agent_view_samples[0].missing_in_agent_view == []


def test_agent_delta_uses_richest_discounted_sample() -> None:
    sampled_pages = [
        ("https://example.com/products/plain", "<html><h1>Plain</h1></html>"),
        (
            "https://example.com/products/variant",
            "<html><h1>Variant</h1><p>25% OFF IN CART</p></html>",
        ),
    ]
    schema_scores = [
        UCPSchemaScore(url=sampled_pages[0][0], product_jsonld_found=True, raw_offers=[{}]),
        UCPSchemaScore(
            url=sampled_pages[1][0],
            product_jsonld_found=True,
            raw_offers=[{}, {}, {}],
        ),
    ]

    assert _best_agent_delta_url(sampled_pages, schema_scores) == sampled_pages[1][0]
