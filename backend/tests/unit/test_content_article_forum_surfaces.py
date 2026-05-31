from __future__ import annotations

from types import SimpleNamespace

import pytest

from bs4 import BeautifulSoup

from app.services.extract.content_listing_handler import validate_table_rows_quality
from app.services.extract.table_extractor import extract_tables
from app.services.pipeline.retry.stage import _apply_detail_rejection_guard
from app.services.pipeline.extract_records import extract_records
from app.services.normalizers import normalize_value
from app.services.public_record_firewall import public_record_data_for_surface


@pytest.mark.unit
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
    assert "# Implementation Guide" in rows[0]["markdown"]
    assert rows[0]["url"] == "https://example.com/docs/guide"


@pytest.mark.unit
def test_content_detail_keeps_markdown_raw_but_not_public_json() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Reference Page</h1>
          <p>Read the <a href="/guide">operator guide</a> before deployment.</p>
        </main></body></html>
        """,
        "https://example.com/docs/reference",
        "content_detail",
        max_records=5,
    )

    data, rejected = public_record_data_for_surface(
        rows[0],
        surface="content_detail",
        page_url="https://example.com/docs/reference",
    )

    assert "[operator guide](https://example.com/guide)" in rows[0]["markdown"]
    assert "markdown" not in data
    assert rejected["markdown"] == "presentation_field_excluded"


@pytest.mark.unit
def test_content_detail_uses_largest_page_content_region() -> None:
    rows = extract_records(
        """
        <html><body>
          <div class="content">
            <h1>First teaser</h1>
            <p>Short first card only.</p>
          </div>
            <div id="pageContent">
              <div class="content">
                <a href="/blog/entry/1">First announcement</a>
                <div>By <a href="/profile/author">Author</a>, 7 days ago,<div class="topic-actions"><ul></ul></div></div>
                <p>This is the first full announcement with enough useful text to matter.</p>
              </div>
            <div class="content">
              <a href="/blog/entry/2">Second announcement</a>
              <p>This is the second full announcement with enough useful text to matter.</p>
            </div>
          </div>
        </body></html>
        """,
        "https://codeforces.com/",
        "content_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert "Short first card only" not in rows[0]["markdown"]
    assert "[First announcement](https://codeforces.com/blog/entry/1)" in rows[0]["markdown"]
    assert "[First announcement](https://codeforces.com/blog/entry/1)\n\nBy" in rows[0]["markdown"]
    assert "By [Author](https://codeforces.com/profile/author), 7 days ago," in rows[0]["markdown"]
    assert "[Second announcement](https://codeforces.com/blog/entry/2)" in rows[0]["markdown"]


@pytest.mark.unit
def test_content_detail_keeps_real_article_that_mentions_bot_terms() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Automation Reference</h1>
          <p>This article compares captcha, hcaptcha, and datadome behavior for
          legitimate documentation. It is normal article content, not a challenge
          page, and should remain extractable as markdown for operators.</p>
          <p>Teams use this material to understand browser automation constraints,
          rate limits, consent flows, request headers, and accessible fallbacks
          across public websites.</p>
        </main></body></html>
        """,
        "https://example.com/docs/bot-terms",
        "content_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert "captcha" in rows[0]["markdown"]


@pytest.mark.unit
def test_content_detail_preserves_syntax_highlighted_code_lines() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Python client</h1>
          <pre><code><span>import</span> <span>asyncio</span>
<span>from</span> <span>parsel</span> <span>import</span> <span>Selector</span>

<span>async</span> <span>def</span> <span>main</span><span>()</span><span>:</span>
    <span>return</span> <span>Selector</span><span>()</span></code></pre>
        </main></body></html>
        """,
        "https://example.com/docs/code",
        "content_detail",
        max_records=5,
    )

    markdown = rows[0]["markdown"]

    assert "```\nimport asyncio\nfrom parsel import Selector" in markdown
    assert "async def main():\n    return Selector()" in markdown
    assert "import\n\nasyncio" not in markdown


@pytest.mark.unit
def test_content_detail_bypasses_ecommerce_shell_rejection_guard() -> None:
    class Context:
        surface = "content_detail"

    class Fetched:
        acquisition_result = object()
        url_metrics = {}

    records = [
        {
            "title": "Codeforces",
            "url": "https://codeforces.com/",
            "markdown": "# Greetings Codeforces\n\nUseful article body.",
            "content": "Greetings Codeforces useful article body.",
        }
    ]

    kept, reason = _apply_detail_rejection_guard(
        Context(),
        Fetched(),
        records=records,
        selector_rules=[],
    )

    assert kept == records
    assert reason is None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_content_detail_skips_detail_repair_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.pipeline import extraction_loop

    async def _fake_extract_records_for_acquisition(context, fetched):
        del context, fetched
        return [{"title": "Docs", "content": "Body", "markdown": "# Docs"}], []

    async def _fake_empty_retry(context, fetched, *, records, selector_rules):
        del context, fetched
        return records, selector_rules

    async def _fake_log_extraction_outcome(_context, _acquisition_result, _records):
        return None

    async def _unexpected_detail_stage(*args, **kwargs):
        del args, kwargs
        raise AssertionError("content_detail should not run detail repair stages")

    monkeypatch.setattr(
        extraction_loop,
        "_extract_records_for_acquisition",
        _fake_extract_records_for_acquisition,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_retry_empty_extraction_with_browser",
        _fake_empty_retry,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_retry_low_quality_extraction_with_browser",
        _unexpected_detail_stage,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_retry_listing_integrity_with_stronger_tier",
        _unexpected_detail_stage,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_apply_extraction_post_processing",
        _unexpected_detail_stage,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_record_detail_expansion_extraction_outcome",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        extraction_loop,
        "_log_extraction_outcome",
        _fake_log_extraction_outcome,
    )

    fetched = SimpleNamespace(
        acquisition_result=SimpleNamespace(method="curl_cffi", browser_diagnostics={}),
        url_metrics={},
    )
    context = SimpleNamespace(surface="content_detail", requested_fields=[])

    extracted = await extraction_loop._run_extraction_stage(context, fetched)

    assert extracted.records == [
        {"title": "Docs", "content": "Body", "markdown": "# Docs"}
    ]


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_content_numeric_fields_normalize_to_integers() -> None:
    assert normalize_value("reply_count", "1,234") == 1234
    assert normalize_value("view_count", "5,678") == 5678
    assert normalize_value("word_count", "901") == 901
    assert normalize_value("reading_time", "12") == 12


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_detail_spec_tables_dedupe_identical_mobile_desktop_copies() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Wrangler Jeans</h1>
          <h2>Size Chart</h2>
          <table>
            <tr><th>Alpha</th><th>Size</th><th>Waist</th></tr>
            <tr><td>XS</td><td>28</td><td>28-29</td></tr>
            <tr><td>S</td><td>30</td><td>30-31</td></tr>
          </table>
          <h2>Size Chart</h2>
          <table>
            <tr><th>Alpha</th><th>Size</th><th>Waist</th></tr>
            <tr><td>XS</td><td>28</td><td>28-29</td></tr>
            <tr><td>S</td><td>30</td><td>30-31</td></tr>
          </table>
        </main></body></html>
        """,
        "https://example.com/products/wrangler-jeans",
        "ecommerce_detail",
        max_records=5,
    )

    assert len(rows) == 1
    assert rows[0]["tables"] == [
        {
            "context": "Size Chart",
            "headers": ["alpha", "size", "waist"],
            "rows": [
                {"alpha": "XS", "size": "28", "waist": "28-29"},
                {"alpha": "S", "size": "30", "waist": "30-31"},
            ],
        }
    ]


@pytest.mark.unit
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


@pytest.mark.unit
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
