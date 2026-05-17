from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.content_listing_handler import validate_table_rows_quality
from app.services.extract.table_extractor import extract_tables
from app.services.extraction_runtime import extract_records
from app.services.normalizers import normalize_value
from app.services.public_record_firewall import public_record_data_for_surface


def test_content_detail_extracts_readable_text() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Implementation Guide</h1>
          <p>This guide explains how teams configure deterministic crawling for internal documentation pages.</p>
        </main></body></html>
        """,
        "https://example.com/docs/guide",
        "content_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["title"] == "Implementation Guide"
    assert "deterministic crawling" in rows[0]["content"]
    assert rows[0]["url"] == "https://example.com/docs/guide"


def test_content_listing_table_rows_keep_open_fields() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <table>
            <tr><th>Country</th><th>Population</th></tr>
            <tr><td>France</td><td>68M</td></tr>
            <tr><td>Japan</td><td>125M</td></tr>
            <tr><td>Brazil</td><td>203M</td></tr>
          </table>
        </main></body></html>
        """,
        "https://example.com/table",
        "content_listing",
        max_records=5,
    )

    assert len(rows) == 3
    assert rows[0]["country"] == "France"
    assert rows[0]["_extraction_mode"] == "table_rows"
    data, rejected = public_record_data_for_surface(
        rows[0],
        surface="content_listing",
        page_url="https://example.com/table",
    )
    assert data["country"] == "France"
    assert "country" not in rejected


def test_content_listing_table_row_quality_rejects_empty_chrome_rows() -> None:
    assert (
        validate_table_rows_quality(
            [
                {
                    "_source": "content_table_rows",
                    "_extraction_mode": "table_rows",
                    "title": "OK",
                },
                {
                    "_source": "content_table_rows",
                    "_extraction_mode": "table_rows",
                    "title": "",
                },
            ]
        )
        is False
    )


def test_content_listing_table_row_urls_stay_aligned_when_tr_is_skipped() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <table>
            <tr><th>Name</th><th>Status</th></tr>
            <tr><td><a href="/skip">Chrome row</a></td></tr>
            <tr><td><a href="/alpha">Alpha</a></td><td>Open</td></tr>
            <tr><td><a href="/beta">Beta</a></td><td>Open</td></tr>
            <tr><td><a href="/gamma">Gamma</a></td><td>Closed</td></tr>
          </table>
        </main></body></html>
        """,
        "https://example.com/table",
        "content_listing",
        max_records=5,
    )

    assert [row["url"] for row in rows] == [
        "https://example.com/alpha",
        "https://example.com/beta",
        "https://example.com/gamma",
    ]


def test_content_listing_does_not_treat_spec_table_as_row_listing() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Yamaha R-N800A Network Receiver</h1>
          <table>
            <tr><th>Brand</th><td>Yamaha</td></tr>
            <tr><th>Model</th><td>R-N800ABL</td></tr>
            <tr><th>Color</th><td>Black</td></tr>
          </table>
        </main></body></html>
        """,
        "https://example.com/products/receiver",
        "content_listing",
        max_records=5,
    )

    assert rows == []


def test_table_context_combines_multiple_aria_labelledby_ids() -> None:
    soup = BeautifulSoup(
        """
        <section>
          <span id="first">Release</span>
          <span id="second">Schedule</span>
          <table aria-labelledby="first second">
            <tr><th>Version</th><th>Date</th></tr>
            <tr><td>1.0</td><td>May</td></tr>
            <tr><td>1.1</td><td>June</td></tr>
          </table>
        </section>
        """,
        "html.parser",
    )

    tables = extract_tables(soup)

    assert tables[0]["context"] == "Release Schedule"


def test_content_numeric_fields_normalize_to_integers() -> None:
    assert normalize_value("reply_count", "1,234") == 1234
    assert normalize_value("view_count", "5,678") == 5678
    assert normalize_value("word_count", "901") == 901
    assert normalize_value("reading_time", "12") == 12


def test_ecommerce_detail_prefers_product_json_ld_over_faq_question_title() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Yamaha R-N800A Network Receiver with Phono and Built-in DAC - Black</h1>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [{
              "@type": "Question",
              "name": "What are the dimensions and weight of the Yamaha R-N800A Network Receiver?"
            }]
          }
          </script>
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "sku": "0ZK-01A6-00390",
            "name": "Yamaha R-N800A Network Receiver with Phono and Built-in DAC - Black",
            "offers": {"@type": "Offer", "price": "749.95", "priceCurrency": "USD"}
          }
          </script>
        </main></body></html>
        """,
        "https://www.newegg.com/yamaha-r-n800abl-receiver/p/0ZK-01A6-00390",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert (
        rows[0]["title"]
        == "Yamaha R-N800A Network Receiver with Phono and Built-in DAC - Black"
    )
    assert rows[0]["sku"] == "0ZK-01A6-00390"


def test_detail_spec_tables_use_field_value_shape() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Yamaha R-N800A Network Receiver</h1>
          <h2>Model</h2>
          <table>
            <tr><th>Brand</th><td>Yamaha</td></tr>
            <tr><th>Model</th><td>R-N800ABL</td></tr>
            <tr><th>Part Number</th><td>R-N800ABL</td></tr>
          </table>
          <h2>Connectivity</h2>
          <table>
            <tr><th>Digital Optical Audio Digital Optical Audio</th><td>Yes</td></tr>
            <tr><th>USB Port USB Port</th><td>USB DAC (USB B-type)</td></tr>
          </table>
        </main></body></html>
        """,
        "https://example.com/products/receiver",
        "ecommerce_detail",
        max_records=5,
    )
    assert len(rows) == 1
    tables = rows[0]["tables"]
    assert len(tables) >= 2
    assert tables[0]["headers"] == ["field", "value"]
    assert tables[0]["context"] == "Model"
    assert tables[0]["rows"][0] == {"field": "Brand", "value": "Yamaha"}
    assert tables[1]["rows"][0] == {"field": "Digital Optical Audio", "value": "Yes"}


def test_article_listing_requires_article_signal() -> None:
    rows = extract_records(
        """
        <html><body>
          <article><h2><a href="/posts/one">Launch Notes</a></h2><time datetime="2026-05-16">May 16</time></article>
          <article><h2><a href="/posts/two">Crawler Patterns</a></h2><p>How extraction tiers stay deterministic.</p></article>
        </body></html>
        """,
        "https://example.com/blog",
        "article_listing",
        max_records=5,
    )

    assert {row["title"] for row in rows} >= {"Launch Notes", "Crawler Patterns"}
    assert all(
        row.get("publication_date") or row.get("summary") or row.get("author")
        for row in rows
    )


def test_forum_detail_extracts_body_and_counts() -> None:
    rows = extract_records(
        """
        <html><body><main class="thread">
          <h1>How do I tune crawls?</h1>
          <div class="post-body">Use explicit surfaces and keep retries bounded.</div>
          <span>12 replies</span><span>140 views</span>
        </main></body></html>
        """,
        "https://forum.example.com/thread/1",
        "forum_detail",
        max_records=5,
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "How do I tune crawls?"
    assert "explicit surfaces" in rows[0]["content"]
    assert rows[0]["reply_count"] == 12
    assert rows[0]["view_count"] == 140
