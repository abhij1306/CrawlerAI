from __future__ import annotations

import pytest

from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs

pytestmark = pytest.mark.component


ACCEPTANCE_SITES = (
    {
        "name": "shop-detail-productgroup",
        "url": "https://acceptance.test/products/aeron-chair",
        "surface": Surface.ECOMMERCE_DETAIL,
        "html": """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "ProductGroup",
            "name": "Aeron Chair",
            "brand": {"@type": "Brand", "name": "Herman Miller"},
            "url": "https://acceptance.test/products/aeron-chair",
            "offers": {
              "@type": "Offer",
              "price": "1495.00",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            },
            "hasVariant": [
              {"@type": "Product", "sku": "AER-BLK-B", "color": "Black", "size": "B"},
              {"@type": "Product", "sku": "AER-GRY-C", "color": "Graphite", "size": "C"}
            ]
          }
          </script>
        </head><body><main><h1>Aeron Chair</h1></main></body></html>
        """,
        "expected": {
            "record_count": 1,
            "fields": {
                "title": "Aeron Chair",
                "brand": "Herman Miller",
                "price": "1495.00",
                "currency": "USD",
            },
            "min_variants": 2,
        },
    },
    {
        "name": "shop-listing-products",
        "url": "https://acceptance.test/collections/chairs",
        "surface": Surface.ECOMMERCE_LISTING,
        "max_records": 5,
        "html": """
        <main>
          <article class="product-card">
            <a href="/products/aeron-chair"><h2>Aeron Chair</h2></a>
            <span class="price">$1495</span>
            <img src="/images/aeron.jpg" alt="Aeron Chair">
          </article>
          <article class="product-card">
            <a href="/products/sayl-chair"><h2>Sayl Chair</h2></a>
            <span class="price">$735</span>
            <img src="/images/sayl.jpg" alt="Sayl Chair">
          </article>
        </main>
        """,
        "expected": {
            "record_count": 2,
            "titles": {"Aeron Chair", "Sayl Chair"},
        },
    },
    {
        "name": "jobs-detail-posting",
        "url": "https://acceptance.test/jobs/staff-backend-engineer",
        "surface": Surface.JOB_DETAIL,
        "html": """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Staff Backend Engineer",
            "hiringOrganization": {"name": "Invoro"},
            "jobLocation": {"address": {"addressLocality": "Remote", "addressCountry": "US"}},
            "datePosted": "2026-06-01",
            "employmentType": "FULL_TIME",
            "description": "Build deterministic extraction systems.",
            "url": "https://acceptance.test/jobs/staff-backend-engineer"
          }
          </script>
        </head><body><main><h1>Staff Backend Engineer</h1></main></body></html>
        """,
        "expected": {
            "record_count": 1,
            "fields": {
                "title": "Staff Backend Engineer",
                "company": "Invoro",
                "location": "Remote, US",
            },
        },
    },
    {
        "name": "jobs-listing-cards",
        "url": "https://acceptance.test/careers",
        "surface": Surface.JOB_LISTING,
        "max_records": 5,
        "html": """
        <ul>
          <li class="job-card">
            <a href="/jobs/backend"><h2>Backend Engineer</h2></a>
            <span class="company">Invoro</span>
            <span class="location">Remote</span>
          </li>
          <li class="job-card">
            <a href="/jobs/data"><h2>Data Engineer</h2></a>
            <span class="company">Invoro</span>
            <span class="location">New York</span>
          </li>
        </ul>
        """,
        "expected": {
            "record_count": 2,
            "titles": {"Backend Engineer", "Data Engineer"},
        },
    },
    {
        "name": "wrong-surface-control",
        "url": "https://acceptance.test/products/not-a-job",
        "surface": Surface.JOB_DETAIL,
        "html": """
        <html><head>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Not A Job",
            "offers": {"@type": "Offer", "price": "10", "priceCurrency": "USD"}
          }
          </script>
        </head><body><main><h1>Not A Job</h1></main></body></html>
        """,
        "expected": {
            "record_count": 0,
            "wrong_surface": True,
        },
    },
)


@pytest.mark.parametrize("site", ACCEPTANCE_SITES, ids=[site["name"] for site in ACCEPTANCE_SITES])
def test_acceptance_replay_site_output_and_traceability(site: dict[str, object]) -> None:
    result = extract(
        fixture_request_from_inputs(
            site["surface"],
            str(site["html"]),
            str(site["url"]),
            max_records=int(site.get("max_records") or 1),
        )
    )
    expected = dict(site["expected"])

    assert result.surface == site["surface"]
    assert len(result.records) == expected["record_count"]

    if expected.get("wrong_surface"):
        assert result.verdict in {"empty", "error", "review"}
        assert not result.records
        assert all(evidence.surface == site["surface"] for evidence in result.evidence)
        return

    assert result.verdict in {"success", "partial"}
    assert result.evidence, site["name"]
    assert result.decisions, site["name"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["evidence"]
    assert payload["decisions"]
    assert all(evidence.subject_id for evidence in result.evidence)
    assert all(evidence.surface == site["surface"] for evidence in result.evidence)

    if "fields" in expected:
        record = result.records[0]
        for field_name, value in dict(expected["fields"]).items():
            assert record.get(field_name) == value
            assert record.get("_lineage", {}).get(field_name), field_name

    if "titles" in expected:
        assert {record.get("title") for record in result.records} == expected["titles"]
        for record in result.records:
            assert record.get("_lineage", {}).get("title")
            assert record.get("_subject_id")

    min_variants = int(expected.get("min_variants") or 0)
    if min_variants:
        variants = result.records[0].model_dump(
            mode="json", exclude_none=True
        ).get("variants")
        assert isinstance(variants, list)
        assert len(variants) >= min_variants
        variant_evidence = [
            item for item in result.evidence if item.fact_type.startswith("variant.")
        ]
        assert variant_evidence
        assert all(item.parent_subject_id for item in variant_evidence)
