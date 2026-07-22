from __future__ import annotations

import pytest

from app.extraction.documents import HtmlDocument, HtmlNode

pytestmark = pytest.mark.unit

_TREE = """
<html><body>
  <div id="grid">
    <section class="card featured" data-kind="a">
      <h2>Alpha <span class="suffix">Pro</span></h2>
      lead<b>bold</b>trail
      <script>var hidden = 1;</script>
    </section>
    <section class="card" data-kind="b">
      <h2>Beta</h2>
      <p hidden>secret</p>
      <p aria-hidden="true">sr-only</p>
      <p style="display: none">invisible</p>
      <script type="application/ld+json">{"price": 10}</script>
    </section>
  </div>
</body></html>
"""


def _first_card(document: HtmlDocument) -> HtmlNode:
    card = document.css_first("section.card")
    assert card is not None
    return card


def test_direct_text_uses_only_direct_text_children() -> None:
    document = HtmlDocument("html", _TREE)
    card = _first_card(document)
    assert card.direct_text() == "lead trail"


def test_child_elements_returns_wrapped_element_children() -> None:
    document = HtmlDocument("html", _TREE)
    card = _first_card(document)
    children = card.child_elements()
    assert [child.tag() for child in children] == ["h2", "b", "script"]
    assert all(isinstance(child, HtmlNode) for child in children)
    assert all(child.artifact_id == "html" for child in children)


def test_previous_element_skips_non_element_siblings() -> None:
    document = HtmlDocument("html", _TREE)
    second_card = document.css("section.card")[1]
    previous = second_card.previous_element()
    assert previous is not None
    assert previous.tag() == "section"
    assert previous.attribute("data-kind") == "a"


def test_attribute_returns_empty_string_for_valueless_attribute() -> None:
    document = HtmlDocument("html", _TREE)
    hidden = document.css_first("p[hidden]")
    assert hidden is not None
    assert hidden.attribute("hidden") == ""
    assert hidden.attribute("missing") is None


def test_dom_path_includes_sibling_indices() -> None:
    document = HtmlDocument("html", _TREE)
    beta = document.css_first("section[data-kind='b'] h2")
    assert beta is not None
    assert beta.dom_path() == "/#document[1]/html[1]/body[1]/div[1]/section[2]/h2[1]"


def test_json_parses_object_payloads_only() -> None:
    document = HtmlDocument("html", _TREE)
    payload = document.css_first("script[type='application/ld+json']")
    assert payload is not None
    assert payload.json() == {"price": 10}
    plain = document.css_first("h2")
    assert plain is not None
    assert plain.json() is None


def test_ancestors_walk_from_nearest_to_root() -> None:
    document = HtmlDocument("html", _TREE)
    beta = document.css_first("section[data-kind='b'] h2")
    assert beta is not None
    tags = [ancestor.tag() for ancestor in beta.ancestors()]
    assert tags[:2] == ["section", "div"]
    assert tags[-1] == "#document"


def test_siblings_empty_for_selectolax_wrapper_identity() -> None:
    # Selectolax returns a fresh wrapper per access, so the original
    # ``node.parent is parent`` identity check never matches and siblings()
    # is always empty. This pins that pre-existing behavior verbatim.
    document = HtmlDocument("html", _TREE)
    card = _first_card(document)
    assert card.siblings() == ()


def test_following_siblings_in_document_order() -> None:
    document = HtmlDocument("html", _TREE)
    card = _first_card(document)
    following = card.following_siblings()
    assert [node.tag() for node in following] == ["-text", "section", "-text"]


def test_stable_locator_prefers_id_then_classes_then_tag() -> None:
    document = HtmlDocument("html", _TREE)
    grid = document.css_first("div")
    assert grid is not None
    assert grid.stable_locator() == "div#grid"
    card = _first_card(document)
    assert card.stable_locator() == "section.card featured"
    paragraph = document.css_first("section[data-kind='b'] p")
    assert paragraph is not None
    assert paragraph.stable_locator() == "p"


def test_is_hidden_detects_hidden_attribute_aria_and_style() -> None:
    document = HtmlDocument("html", _TREE)
    card = _first_card(document)
    assert card.is_hidden() is False
    by_hidden = document.css_first("p[hidden]")
    assert by_hidden is not None and by_hidden.is_hidden() is True
    by_aria = document.css_first("p[aria-hidden='true']")
    assert by_aria is not None and by_aria.is_hidden() is True
    by_style = document.css_first("p[style]")
    assert by_style is not None and by_style.is_hidden() is True
