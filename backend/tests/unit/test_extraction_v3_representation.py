from __future__ import annotations

from app.extraction.documents import HtmlDocument
from app.extraction.representation import build_flat_map, build_scoped_flat_map, ground


def test_flat_map_uses_absolute_paths_and_text_only() -> None:
    document = HtmlDocument(
        "html",
        """
        <html><body>
          <main id="pdp" style="display:block">
            <h1 class="name">Trail Shoe</h1>
            <script>{"price": "999"}</script>
            <p>Fast hiking shoe</p>
          </main>
        </body></html>
        """,
    )

    flat_map = build_flat_map(document)

    assert "/html[1]/body[1]/main[1]/h1[1]" in flat_map
    assert flat_map["/html[1]/body[1]/main[1]/h1[1]"] == "Trail Shoe"
    assert all("script" not in path for path in flat_map)
    assert all("class" not in path and "style" not in path for path in flat_map)


def test_scoping_falls_back_when_region_is_too_small() -> None:
    document = HtmlDocument(
        "html",
        """
        <html><body>
          <main><h1>Trail Shoe</h1></main>
          <section>
            <p>Price $19.98</p>
            <p>SKU RUN-1</p>
            <p>Description has enough useful product words for fallback.</p>
          </section>
        </body></html>
        """,
    )

    scoped = build_scoped_flat_map(document)

    assert scoped.fallback_reason == "scoped_region_below_min_tokens"
    assert scoped.token_count > 0
    assert scoped.scope_path is None


def test_grounding_exact_normalized_and_miss() -> None:
    flat_map = build_flat_map(
        HtmlDocument(
            "html",
            """
            <html><body>
              <main><h1>Trail Shoe</h1><p>Price $19.98</p></main>
            </body></html>
            """,
        )
    )

    exact = ground("Trail Shoe", flat_map)
    normalized = ground("1998", flat_map)
    miss = ground("Imaginary Product", flat_map)

    assert exact.grounded is True
    assert exact.match_type == "exact"
    assert normalized.grounded is True
    assert normalized.match_type == "normalized"
    assert miss.grounded is False
    assert miss.match_type == "none"
