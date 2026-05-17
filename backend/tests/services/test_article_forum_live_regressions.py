from __future__ import annotations

from app.services.acquisition.runtime import classify_blocked_page
from app.services.extraction_runtime import extract_records


def test_content_detail_preserves_main_inside_sidebar_named_layout() -> None:
    rows = extract_records(
        """
        <html><body>
          <div class="layout__2-sidebars-inline">
            <main id="content">
              <h1>Introduction</h1>
              <p>This guide contains durable documentation prose that must remain after
              sidebar navigation is removed from the page.</p>
              <p>The extractor should keep the central main content, not the page shell.</p>
            </main>
          </div>
        </body></html>
        """,
        "https://developer.example/docs/intro",
        "content_detail",
        max_records=5,
    )

    assert rows
    assert "durable documentation prose" in rows[0]["content"]
    assert rows[0]["word_count"] >= 20


def test_article_detail_preserves_main_when_body_class_says_no_sidebar() -> None:
    rows = extract_records(
        """
        <html><body class="single-post no-sidebar">
          <main>
            <article class="post">
              <h1>Highlights from Git</h1>
              <time datetime="2025-06-16">June 16, 2025</time>
              <p>Git releases include performance improvements and maintenance updates.</p>
              <p>This article body is the canonical content and should not be deleted.</p>
            </article>
          </main>
        </body></html>
        """,
        "https://example.com/open-source/git/highlights",
        "article_detail",
        max_records=5,
        requested_fields=["title", "content", "publication_date"],
    )

    assert rows
    assert "canonical content" in rows[0]["content"]
    assert rows[0]["publication_date"] == "2025-06-16"


def test_article_detail_uses_largest_article_body_candidate() -> None:
    rows = extract_records(
        """
        <html><body>
          <main>
            <article><h2>Related post</h2><p>Small teaser only.</p></article>
            <article class="post">
              <h1>Highlights from Git</h1>
              <time datetime="2025-06-16">June 16, 2025</time>
              <p>Git releases include performance improvements and maintenance updates.</p>
              <p>This long article body is the canonical content and should win over
              short related-card article elements.</p>
            </article>
          </main>
        </body></html>
        """,
        "https://example.com/open-source/git/highlights",
        "article_detail",
        max_records=5,
        requested_fields=["title", "content", "publication_date"],
    )

    assert rows
    assert "canonical content" in rows[0]["content"]
    assert "Small teaser only" not in rows[0]["content"]


def test_article_detail_extracts_publication_date_from_date_class() -> None:
    rows = extract_records(
        """
        <html><body>
          <main>
            <article>
              <h1>Temporal Is Coming</h1>
              <div class="date">July 12, 2024</div>
              <p>Temporal simplifies date and time handling for JavaScript applications.</p>
              <p>Developers can use it to model instants, dates, and time zones.</p>
            </article>
          </main>
        </body></html>
        """,
        "https://developer.example/blog/temporal",
        "article_detail",
        max_records=5,
        requested_fields=["title", "content", "publication_date"],
    )

    assert rows
    assert rows[0]["publication_date"] == "July 12, 2024"


def test_article_detail_uses_original_dom_when_cleaned_dom_drops_date() -> None:
    rows = extract_records(
        """
        <html><body>
          <main>
            <article>
              <h1>Temporal Is Coming</h1>
              <div class="date">January 24, 2025</div>
              <p>Temporal simplifies date and time handling for JavaScript applications.</p>
              <p>Developers can use it to model instants, dates, and time zones.</p>
            </article>
          </main>
        </body></html>
        """,
        "https://developer.example/blog/temporal",
        "article_detail",
        max_records=5,
        requested_fields=["title", "content", "publication_date"],
    )

    assert rows
    assert rows[0]["publication_date"] == "January 24, 2025"


def test_content_listing_does_not_fall_back_to_related_links_when_table_shape_rejected() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Reference Table</h1>
          <table>
            <tr><th>Code</th><th>Meaning</th></tr>
            <tr><td>100</td><td>Continue</td></tr>
            <tr><td>101</td><td>Switching Protocols</td></tr>
          </table>
          <section>
            <h2>See also</h2>
            <a href="/related-a">Related A</a>
            <a href="/related-b">Related B</a>
            <a href="/related-c">Related C</a>
          </section>
        </main></body></html>
        """,
        "https://example.com/reference/table",
        "content_listing",
        max_records=10,
    )

    assert rows == []


def test_content_listing_filters_hacker_news_chrome_rows() -> None:
    rows = extract_records(
        """
        <html><body>
          <table>
            <tr class="athing"><td><a href="https://example.com/story">Useful Story</a></td></tr>
            <tr><td>50 minutes ago</td></tr>
            <tr><td><a href="news">Hacker News</a></td></tr>
            <tr><td><a href="https://www.ycombinator.com/apply">Apply to YC</a></td></tr>
            <tr class="athing"><td><a href="https://example.com/other">Another Useful Story</a></td></tr>
          </table>
        </body></html>
        """,
        "https://news.ycombinator.com/news",
        "content_listing",
        max_records=10,
    )

    titles = {row.get("title") for row in rows}
    assert "Useful Story" in titles
    assert "Another Useful Story" in titles
    assert "Hacker News" not in titles
    assert "Apply to YC" not in titles
    assert "50 minutes ago" not in titles


def test_article_listing_extracts_post_card_with_nearby_date() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <article class="post-card">
            <h2><a href="/open-source/git/highlights">Highlights from Git 2.50</a></h2>
            <time datetime="2025-06-16">June 16, 2025</time>
            <p>A tour of the most useful updates in this Git release.</p>
          </article>
          <article class="post-card">
            <h2><a href="/engineering/platform-update">Platform Update</a></h2>
            <time datetime="2025-06-15">June 15, 2025</time>
            <p>Engineering updates from the platform team.</p>
          </article>
        </main></body></html>
        """,
        "https://github.example/blog",
        "article_listing",
        max_records=10,
    )

    assert {row["title"] for row in rows} >= {
        "Highlights from Git 2.50",
        "Platform Update",
    }
    assert all(row.get("publication_date") for row in rows)


def test_reddit_verification_page_is_classified_blocked() -> None:
    result = classify_blocked_page(
        """
        <html>
          <head><title>Reddit - Please wait for verification</title></head>
          <body><main></main></body>
        </html>
        """,
        200,
    )

    assert result.blocked
    assert result.outcome == "challenge_page"


def test_forum_detail_extracts_reddit_text_body_slot() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Python 3.13 released</h1>
          <article></article>
          <shreddit-post>
            <div slot="text-body">
              <p>This is the stable release of Python 3.13.0.</p>
              <p>Python 3.13.0 is the newest major release of the Python programming language.</p>
            </div>
          </shreddit-post>
        </main></body></html>
        """,
        "https://www.reddit.example/r/Python/comments/1fybncq",
        "forum_detail",
        max_records=5,
        requested_fields=["title", "content", "url"],
    )

    assert rows
    assert "stable release of Python 3.13.0" in rows[0]["content"]
