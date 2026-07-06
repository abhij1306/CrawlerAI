# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


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


def test_job_detail_wrong_surface_product_returns_error_without_commerce_aliases() -> (
    None
):
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Trail Shoe",
      "offers": {"@type": "Offer", "price": "129", "priceCurrency": "USD"}
    }
    </script>
    """
    result = _extract("job_detail", html, "https://jobs.test/not-a-job")
    assert result.verdict == "wrong_surface"
    assert not result.records
    assert {finding.rule_id for finding in result.findings} == {"WRONG_SURFACE_CONTENT"}


def test_job_detail_result_is_replayable() -> None:
    result = _extract(
        "job_detail",
        """
        <main>
          <h1>Staff Backend Engineer</h1>
          <div class="company">Invoro</div>
          <div class="location">Remote</div>
          <a href="/apply/staff-backend-engineer">Apply</a>
        </main>
        """,
        "https://jobs.test/staff-backend-engineer",
        max_records=1,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Staff Backend Engineer"
    assert rows[0]["apply_url"] == "https://jobs.test/apply/staff-backend-engineer"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_detail"
    assert payload["evidence"]
    assert payload["decisions"]


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
    assert {row["title"] for row in result.records} == {
        "Backend Engineer",
        "Data Engineer",
    }
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_listing" for item in result.evidence)


def test_job_listing_result_is_replayable() -> None:
    result = _extract(
        "job_listing",
        """
        <article class="job-card">
          <a href="/jobs/backend" title="Backend Engineer">Backend Engineer</a>
          <span class="company">Invoro</span>
        </article>
        """,
        "https://jobs.test/careers",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Backend Engineer"
    assert rows[0]["url"] == "https://jobs.test/jobs/backend"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_listing"
    assert payload["evidence"]
    assert payload["decisions"]


def test_job_listing_greenhouse_table_rows_materialize() -> None:
    result = _extract(
        "job_listing",
        """
        <main><table>
          <tr class="job-post">
            <td class="cell">
              <a href="https://careers.test/positions/123">
                <p class="body body--medium">Senior Data Scientist</p>
                <p class="body body__secondary body--metadata">Remote</p>
              </a>
            </td>
          </tr>
        </table></main>
        """,
        "https://job-boards.test/embed/job_board?for=company",
        max_records=5,
    )
    assert result.records
    assert result.records[0]["title"] == "Senior Data Scientist"
    assert result.records[0]["url"] == "https://careers.test/positions/123"
    assert result.records[0]["location"] == "Remote"


def test_parent_mixed_variant_prices_publish_explicit_range_semantics() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "25",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {"price": "20", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {"price": "25", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    record = result.records[0]
    assert record["price"] == "25.00"
    assert record["price_min"] == "20.00"
    assert record["price_max"] == "25.00"
    assert (
        record["_lineage"]["price_min"]["rule_id"] == "minimum_variant_price_aggregate"
    )


def test_direct_parent_price_is_not_replaced_by_variant_aggregate() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Relaxed-Fit Printed T-Shirt",
          "url": "https://shop.test/products/printed-tee",
          "offers": {"price": "84.99", "priceCurrency": "USD"},
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "BLUE",
              "color": "Blue",
              "offers": {"price": "84.99", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "BLUE-S",
              "color": "Blue",
              "size": "S",
              "offers": {"price": "12.99", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "BLUE-M",
              "color": "Blue",
              "size": "M",
              "offers": {"price": "12.99", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/printed-tee",
    )

    record = result.records[0]
    assert record["price"] == "84.99"
    assert record.get("price_min") in (None, "12.99")
    assert record.get("price_max") in (None, "12.99")


def test_complete_variant_matrix_derives_parent_family_availability() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "20",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock"
              }
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    record = result.records[0]
    assert record["availability"] == "in_stock"
    assert (
        record["_lineage"]["availability"]["rule_id"]
        == "variant_availability_aggregate"
    )
    assert not any(
        finding.rule_id == "PARENT_VARIANT_AVAILABILITY_CONFLICT"
        for finding in result.findings
    )


def test_incomplete_variant_identity_is_diagnostic_not_public_row() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {"price": "20", "priceCurrency": "USD"},
          "hasVariant": [
            {"@type": "Product", "url": "https://shop.test/products/everyday-tee?variant=1"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    assert not result.records[0].get("variants")
    assert any(
        finding.rule_id == "INCOMPLETE_VARIANT_EVIDENCE" for finding in result.findings
    )


def test_non_positive_price_is_not_successful_public_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trial Pack",
          "url": "https://shop.test/products/trial-pack",
          "offers": {"price": "0.00", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trial-pack",
    )
    assert result.records[0].get("price") is None
    assert result.verdict != "success"
    assert any(finding.rule_id == "NON_POSITIVE_PRICE" for finding in result.findings)


def test_wrong_product_detail_identity_is_dropped_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Related Shirt",
          "url": "https://shop.test/products/related-shirt",
          "offers": {"price": "29.00", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/primary-cap",
    )

    assert result.verdict in {"empty", "invalid"}
    assert not result.records
    assert result.target.status == "missing"
    assert any(
        row.reason == "identity_mismatch" for row in result.target.rejected_roots
    )


def test_parent_availability_does_not_override_incomplete_variant_matrix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "20",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {"@type": "Product", "url": "https://shop.test/products/everyday-tee?variant=2"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    assert result.records[0]["availability"] == "out_of_stock"
    assert (
        result.records[0]["_lineage"]["availability"]["rule_id"]
        != "variant_availability_aggregate"
    )
