from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.extraction import Surface, extract
from app.services.extraction.contracts import Evidence
from app.services.extraction.replay import request_from_inputs
from app.services.pipeline.extract_records import extract_records

pytestmark = pytest.mark.unit


HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trail Shoe",
  "brand": {"@type": "Brand", "name": "Invoro"},
  "sku": "TS-1",
  "url": "https://shop.test/products/trail-shoe",
  "image": ["https://shop.test/i/trail.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "129",
    "priceCurrency": "usd",
    "availability": "https://schema.org/InStock"
  },
  "hasVariant": [
    {"@type": "Product", "sku": "TS-1-BLK-9", "color": "Black", "size": "9"}
  ]
}
</script>
</head>
<body><main><h1>Trail Shoe</h1></main></body>
</html>
"""


def _extract(
    surface: str,
    html: str,
    page_url: str,
    *,
    max_records: int = 1,
    artifacts: dict[str, object] | None = None,
):
    return extract(
        request_from_inputs(
            Surface(surface),
            html,
            page_url,
            max_records=max_records,
            artifacts=artifacts,
        )
    )


def test_materializes_once_with_lineage_and_quality() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["title"] == "Trail Shoe"
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["_quality_verdict"] == "success"
    assert record["_lineage"]["price"]["derived_fact_id"]
    assert result.evidence
    assert result.decisions


def test_evidence_is_immutable() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    item = result.evidence[0]
    try:
        item.value = "changed"  # type: ignore[misc]
    except (ValidationError, TypeError):
        pass
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/trail-shoe")
    assert not result.records
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in result.findings}


def test_order_and_duplicate_independence() -> None:
    duplicate = HTML.replace("</head>", HTML.split("<script", 1)[1].join(["<script", "</head>"]))
    first = tuple(_extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe").records)
    second = tuple(_extract("ecommerce_detail", duplicate, "https://shop.test/products/trail-shoe").records)
    assert first == second


def test_ecommerce_detail_cutover_uses_replay_artifact() -> None:
    artifacts: dict[str, object] = {}
    rows = extract_records(
        HTML,
        "https://shop.test/products/trail-shoe",
        "ecommerce_detail",
        max_records=1,
        artifacts=artifacts,
    )
    assert rows and rows[0]["title"] == "Trail Shoe"
    assert "extraction_replay" in artifacts


def test_ecommerce_listing_cutover_materializes_with_lineage() -> None:
    html = """
    <main>
      <article class="product-card">
        <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
        <span class="price">$129.00</span>
        <img src="/images/trail.jpg">
      </article>
      <article class="product-card">
        <a href="/products/day-pack"><h2>Day Pack</h2></a>
        <span class="price">$89.00</span>
      </article>
    </main>
    """
    result = _extract(
        "ecommerce_listing",
        html,
        "https://shop.test/collections/all",
        max_records=5,
    )
    assert result.verdict == "success"
    assert result.evidence
    assert result.decisions
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "ecommerce_listing" for item in result.evidence)


def test_ecommerce_listing_extract_records_writes_replay() -> None:
    artifacts: dict[str, object] = {}
    rows = extract_records(
        """
        <section>
          <div class="product-tile">
            <a href="/products/trail-shoe" title="Trail Shoe">Trail Shoe</a>
            <div data-price="129.00"></div>
          </div>
        </section>
        """,
        "https://shop.test/collections/all",
        "ecommerce_listing",
        max_records=3,
        artifacts=artifacts,
    )
    assert rows == [
        {
            "title": "Trail Shoe",
            "url": "https://shop.test/products/trail-shoe",
            "price": "129.00",
            "_lineage": rows[0]["_lineage"],
            "_subject_id": rows[0]["_subject_id"],
        }
    ]
    replay = artifacts.get("extraction_replay")
    assert isinstance(replay, dict)
    assert replay["surface"] == "ecommerce_listing"
    assert replay["evidence"]
    assert replay["decisions"]


def test_js_state_dict_values_do_not_crash_dedupe() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": {"text": "Rustic Cotton T-Shirt"},
                "price": {"value": "29.90"},
                "currency": "USD",
            }
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Fallback</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["price"] == "29.90"
    assert result.evidence


def test_js_state_explicit_variant_rows_are_materialized() -> None:
    artifacts = {
        "js_state_objects": {
            "variants": [
                {"id": "v1", "sku": "SKU-BLK-S", "size": "S", "color": "Black"},
                {"id": "v2", "sku": "SKU-WHT-M", "size": "M", "color": "White"},
            ]
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Rustic Cotton T-Shirt</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["variants"] == [
        {"selected": False, "sku": "SKU-BLK-S", "color": "Black", "size": "S"},
        {"selected": False, "sku": "SKU-WHT-M", "color": "White", "size": "M"},
    ]


def test_product_group_variants_have_lineage_and_parent_subjects() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"},
        {"@type": "Product", "sku": "TEE-BLK-M", "color": "Black", "size": "M"}
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/everyday-tee")
    assert result.verdict == "success"
    assert result.records[0]["variants"] == [
        {"selected": False, "sku": "TEE-BLK-S", "color": "Black", "size": "S"},
        {"selected": False, "sku": "TEE-BLK-M", "color": "Black", "size": "M"},
    ]
    variant_evidence = [item for item in result.evidence if item.fact_type.startswith("variant.")]
    assert variant_evidence
    assert all(item.subject_id for item in variant_evidence)
    assert all(item.parent_subject_id for item in variant_evidence)


def test_dom_variant_controls_do_not_succeed_with_missing_variants() -> None:
    html = """
    <main>
      <h1>Everyday Tee</h1>
      <select name="size">
        <option>Select size</option>
        <option>S</option>
        <option>M</option>
      </select>
      <button data-option-name="color">Black</button>
    </main>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/everyday-tee")
    assert result.records
    assert result.records[0]["variants"]
    variant_evidence = [item for item in result.evidence if item.fact_type.startswith("variant.")]
    assert all(item.parent_subject_id for item in variant_evidence)


def test_mixed_numeric_and_string_identity_values_do_not_crash() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": "Rustic Cotton T-Shirt",
                "sku": 123,
                "price": "29.90",
                "currency": "USD",
            }
        }
    }
    html = '<html><body><h1>Rustic Cotton T-Shirt</h1><div data-sku="123"></div></body></html>'
    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["sku"] in {123, "123"}


def test_adapter_artifact_flows_through_evidence_engine() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/adapter-widget",
        artifacts={
            "adapter_artifacts": [
                {
                    "artifact_type": "adapter_json",
                    "adapter_name": "legacy",
                    "body": {
                        "title": "Adapter Widget",
                        "sku": "AD-1",
                        "price": "10.00",
                        "currency": "USD",
                    },
                }
            ]
        },
    )
    assert result.records
    assert result.records[0]["title"] == "Adapter Widget"
    assert result.records[0]["_lineage"]["title"]
    assert any(item.artifact_id == "adapter_0" for item in result.evidence)


def test_job_detail_cutover_materializes_with_lineage() -> None:
    html = """
    <html>
      <head>
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
          "url": "https://jobs.test/staff-backend-engineer"
        }
        </script>
      </head>
      <body><main><h1>Fallback Title</h1></main></body>
    </html>
    """
    result = _extract("job_detail", html, "https://jobs.test/staff-backend-engineer")
    assert result.verdict == "success"
    assert result.records[0]["title"] == "Staff Backend Engineer"
    assert result.records[0]["company"] == "Invoro"
    assert result.records[0]["location"] == "Remote, US"
    assert result.records[0]["_lineage"]["title"]
    assert result.evidence
    assert result.decisions
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_detail" for item in result.evidence)


def test_job_detail_extract_records_writes_replay() -> None:
    artifacts: dict[str, object] = {}
    rows = extract_records(
        """
        <main>
          <h1>Staff Backend Engineer</h1>
          <div class="company">Invoro</div>
          <div class="location">Remote</div>
          <a href="/apply/staff-backend-engineer">Apply</a>
        </main>
        """,
        "https://jobs.test/staff-backend-engineer",
        "job_detail",
        max_records=1,
        artifacts=artifacts,
    )
    assert rows and rows[0]["title"] == "Staff Backend Engineer"
    assert rows[0]["apply_url"] == "https://jobs.test/apply/staff-backend-engineer"
    assert rows[0]["_lineage"]["title"]
    replay = artifacts.get("extraction_replay")
    assert isinstance(replay, dict)
    assert replay["surface"] == "job_detail"
    assert replay["evidence"]
    assert replay["decisions"]


def test_job_listing_cutover_materializes_with_lineage() -> None:
    result = _extract(
        "job_listing",
        """
        <ul>
          <li class="job-card">
            <a href="/jobs/backend"><h2>Backend Engineer</h2></a>
            <span class="company">Invoro</span>
            <span class="location">Remote</span>
          </li>
          <li class="job-card">
            <a href="/jobs/data"><h2>Data Engineer</h2></a>
            <span class="company">Invoro</span>
          </li>
        </ul>
        """,
        "https://jobs.test/careers",
        max_records=5,
    )
    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {"Backend Engineer", "Data Engineer"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_listing" for item in result.evidence)


def test_job_listing_extract_records_writes_replay() -> None:
    artifacts: dict[str, object] = {}
    rows = extract_records(
        """
        <article class="job-card">
          <a href="/jobs/backend" title="Backend Engineer">Backend Engineer</a>
          <span class="company">Invoro</span>
        </article>
        """,
        "https://jobs.test/careers",
        "job_listing",
        max_records=3,
        artifacts=artifacts,
    )
    assert rows and rows[0]["title"] == "Backend Engineer"
    assert rows[0]["url"] == "https://jobs.test/jobs/backend"
    assert rows[0]["_lineage"]["title"]
    replay = artifacts.get("extraction_replay")
    assert isinstance(replay, dict)
    assert replay["surface"] == "job_listing"
    assert replay["evidence"]
    assert replay["decisions"]
