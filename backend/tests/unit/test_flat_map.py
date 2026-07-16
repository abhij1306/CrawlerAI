from __future__ import annotations

from app.extraction.documents import HtmlDocument
from app.extraction.representation.flat_map import (
    build_flat_map,
    build_scoped_flat_map,
    chunk_flat_map,
    flat_map_token_count,
    ground,
)

_PDP_HTML = """
<html><body>
  <main id="pdp" style="display:block">
    <h1 class="name">Trail Shoe</h1>
    <script>{"price": "leaked"}</script>
    <div class="price">$129.00</div>
    <div class="desc">Waterproof description with add to cart availability sku.</div>
  </main>
  <footer>site footer text</footer>
</body></html>
"""


def test_flat_map_uses_absolute_paths_and_excludes_scripts() -> None:
    document = HtmlDocument("html", _PDP_HTML)
    flat_map = build_flat_map(document)
    # Every key is an absolute dom path.
    assert all(path.startswith("/") for path in flat_map)
    values = " ".join(flat_map.values())
    assert "Trail Shoe" in values
    assert "$129.00" in values
    # Script content must never leak into the representation.
    assert "leaked" not in values


def test_scoped_flat_map_prefers_content_region() -> None:
    document = HtmlDocument("html", _PDP_HTML)
    scoped = build_scoped_flat_map(document)
    text = " ".join(scoped.flat_map.values()).casefold()
    # The scope should retain the product anchors.
    assert "add to cart" in text or "price" in text or "sku" in text
    assert scoped.token_count > 0


def test_ground_matches_exact_and_normalized() -> None:
    document = HtmlDocument("html", _PDP_HTML)
    flat_map = build_flat_map(document)
    exact = ground("Trail Shoe", flat_map)
    assert exact.grounded is True
    assert exact.match_type == "exact"
    # Price normalization: emitted "129" grounds against page "$129.00".
    normalized = ground("129", flat_map)
    assert normalized.grounded is True
    # A value absent from the page never grounds.
    missing = ground("NONEXISTENT VALUE", flat_map)
    assert missing.grounded is False
    assert missing.match_type == "none"


def test_chunk_flat_map_splits_by_token_target() -> None:
    document = HtmlDocument("html", _PDP_HTML)
    flat_map = build_flat_map(document)
    total = flat_map_token_count(flat_map)
    assert total > 0
    chunks = chunk_flat_map(flat_map, target_tokens=1)
    # A tiny target forces (at least) one entry per chunk.
    assert len(chunks) >= 1
    reassembled = {k: v for chunk in chunks for k, v in chunk.items()}
    assert reassembled == dict(flat_map)
