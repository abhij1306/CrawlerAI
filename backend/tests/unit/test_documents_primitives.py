from __future__ import annotations

from app.extraction.documents import HtmlDocument

_TREE = """
<html><body>
  <ul id="grid">
    <li class="card"><a href="/a">Alpha</a></li>
    <li class="card"><a href="/b">Beta</a></li>
  </ul>
  <div id="mixed">visible<script>hidden_script</script><style>.x{color:red}</style>tail</div>
</body></html>
"""


def test_child_elements_returns_direct_element_children_only() -> None:
    document = HtmlDocument("html", _TREE)
    grid = document.css_first("#grid")
    assert grid is not None
    children = grid.child_elements()
    assert len(children) == 2
    assert all(child.tag() == "li" for child in children)


def test_content_text_excludes_script_and_style() -> None:
    document = HtmlDocument("html", _TREE)
    mixed = document.css_first("#mixed")
    assert mixed is not None
    text = mixed.content_text()
    assert "visible" in text
    assert "tail" in text
    assert "hidden_script" not in text
    assert "color:red" not in text
