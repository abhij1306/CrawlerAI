"""test_crawl_run_95_regressions cases split by public behavior."""

from __future__ import annotations

from tests.unit.crawl_run_95_test_support import (
    CommerceDetailProjection,
    PublicationEntry,
    _CONTROL_ROLE_HTML,
    _dom_option_values,
    _extract,
    _request,
    _variant_group_html,
    _variant_json,
    projection_field_states,
)


def test_variant_prices_do_not_publish_parent_commercial_fields() -> None:
    """Slice 1: results 68/90 — published variant offers must not mark the
    public parent (``record.*``) field as published.

    The defect was that ``projection_field_states`` flattened ``variant[...].price``
    into the ``price`` group, so a published variant price reported the page-level
    ``price`` as ``captured_published`` even though ``record.price`` was absent.
    After the fix variant facts are summarized under ``variants.*`` and never
    inflate the parent field's state.
    """
    projection = CommerceDetailProjection(
        record_entity_id="product:1",
        variant_entity_ids=("offer:v1", "offer:v2"),
        entries=(
            PublicationEntry(
                path="record.title",
                entity_id="product:1",
                value="Norvan Trail Shoe",
                selected_fact_id="sel:title",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v1].price",
                entity_id="offer:v1",
                value="150.00",
                selected_fact_id="sel:p1",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v1].currency",
                entity_id="offer:v1",
                value="USD",
                selected_fact_id="sel:c1",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v2].price",
                entity_id="offer:v2",
                value="170.00",
                selected_fact_id="sel:p2",
                disposition="publish",
            ),
            PublicationEntry(
                path="variant[offer:v2].availability",
                entity_id="offer:v2",
                value="InStock",
                selected_fact_id="sel:a2",
                disposition="publish",
            ),
        ),
    )

    states = {
        state.field: state.state
        for state in projection_field_states(
            projection,
            (),
            (),
            _request("title", "price", "currency", "availability"),
            (),
        )
    }

    # Parent commercial fields have no published parent entry -> must be absent.
    assert states["price"] == "not_present_in_captured_sources"
    assert states["currency"] == "not_present_in_captured_sources"
    assert states["availability"] == "not_present_in_captured_sources"

    # The variant facts are summarized separately and remain visible.
    assert states["variants.price"] == "captured_published"
    assert states["variants.currency"] == "captured_published"
    assert states["variants.availability"] == "captured_published"


def test_published_parent_price_still_reports_captured_published() -> None:
    """A genuine ``record.price`` publish entry must still surface as published —
    the Slice 1 split must not suppress real parent facts."""
    projection = CommerceDetailProjection(
        record_entity_id="product:1",
        entries=(
            PublicationEntry(
                path="record.price",
                entity_id="offer:1",
                value="150.00",
                selected_fact_id="sel:p",
                disposition="publish",
            ),
        ),
    )

    states = {
        state.field: state.state
        for state in projection_field_states(projection, (), (), _request("price"), ())
    }

    assert states["price"] == "captured_published"


def test_non_product_select_controls_create_no_option_axes() -> None:
    """Slice 2: sort, country, quantity and review-filter selects must never
    become size/color axes; genuine size/color selects still do (results
    10/17/21/58/70/79/95 lost axes; 11/12/20/25/30/75 kept them)."""
    result = _extract(
        "ecommerce_detail",
        _CONTROL_ROLE_HTML,
        "https://shop.test/p",
        requested_fields=("title", "price"),
    )
    values = _dom_option_values(result)

    # Legitimate product options survive.
    assert {"9", "10", "11"} <= values.get("option.size", set())
    assert values.get("option.color", set()) == {"Black", "Red"}

    # Control-select values must not have leaked into any option axis.
    leaked = set().union(*values.values()) if values else set()
    for control_value in (
        "Featured",
        "Price: Low to High",
        "United States",
        "Canada",
        "Most recent",
        "Highest rated",
        "1",
        "2",
        "3",
    ):
        assert control_value not in leaked, control_value


def test_control_role_classifier_rejects_and_admits_generically() -> None:
    """The role classifier is site-agnostic: reject-tokens win, product-option
    tokens admit, bare selects stay out."""
    from app.core.config.extraction_rules import (
        control_signal_tokens,
        has_product_option_signal,
        is_rejected_control,
    )

    sort = control_signal_tokens(["oke-sortSelect--reviews", "Sort"])
    assert is_rejected_control(sort)

    country = control_signal_tokens(["country_code", "CountryList"])
    assert is_rejected_control(country)

    size = control_signal_tokens(["size", "product-size"])
    assert not is_rejected_control(size)
    assert has_product_option_signal(size, axis="size")

    colour = control_signal_tokens(["product-option-colour", "Colour"])
    assert not is_rejected_control(colour)
    assert has_product_option_signal(colour, axis="color")

    # Bare/opaque select: no reject signal, but also no product-option signal.
    opaque = control_signal_tokens(["kib-field-29722"])
    assert not is_rejected_control(opaque)
    assert not has_product_option_signal(opaque, axis="")


def test_colour_and_wrapped_select_controls_create_color_axis() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><body><main>
          <h1>Trail Shoe</h1>
          <form class="product-form">
            <label>Colour
              <select name="product-colour">
                <option>Black</option><option>Bone</option>
              </select>
            </label>
            <select data-option-name="Colour"><option>Red</option></select>
            <button data-option-name="colour">Blue</button>
          </form>
        </main></body></html>
        """,
        "https://shop.test/p",
        requested_fields=("title",),
    )

    assert _dom_option_values(result).get("option.color", set()) == {
        "Black",
        "Bone",
        "Red",
        "Blue",
    }


def test_select_label_lookup_ignores_css_special_id_without_crashing() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><body><main>
          <h1>Trail Shoe</h1>
          <label for='product&quot;\\colour'>Colour</label>
          <span>Choose an option</span>
          <select id='product&quot;\\colour'><option>Black</option></select>
        </main></body></html>
        """,
        "https://shop.test/p",
        requested_fields=("title",),
    )

    assert _dom_option_values(result).get("option.color", set()) == {"Black"}


def test_embedded_variant_offers_bind_per_variant_not_collapsed() -> None:
    """Slice 3 (results 68/90/23): each ``hasVariant[N].offers`` node shares the
    product URL as its offer identity. They must each bind to their own variant
    (so every variant keeps its price) instead of collapsing into a single offer
    bound to one variant, which left the parent commercial fields blank."""
    variants = ", ".join(
        _variant_json(f"SKU-{i}", str(size), price="260.00", availability="InStock")
        for i, size in enumerate(("7", "8", "9", "10"))
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "currency", "availability", "variants"),
    )
    record = result.records[0]
    variant_rows = record.get("variants") or ()
    assert len(variant_rows) == 4
    assert all(row.get("price") == "260.00" for row in variant_rows)

    # Complete, uniform catalog -> parent aggregates the shared price/availability.
    assert record.get("price") == "260.00"
    assert record.get("currency") == "CAD"
    assert record.get("availability") == "in_stock"


def test_parent_availability_rolls_up_mixed_variant_states() -> None:
    """Slice 3: a complete catalog whose variants mix ``in_stock`` /
    ``out_of_stock`` / ``limited_stock`` must publish a purchasable parent state
    (``in_stock`` wins) rather than dropping availability because a non-binary
    state (``limited_stock``, result 68) was present."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="260.00", availability="InStock"),
            _variant_json("SKU-B", "8", price="260.00", availability="OutOfStock"),
            _variant_json(
                "SKU-C", "9", price="260.00", availability="LimitedAvailability"
            ),
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "availability", "variants"),
    )
    record = result.records[0]
    assert record.get("availability") == "in_stock"
    assert (
        record["_lineage"]["availability"]["rule_id"]
        == "variant_availability_aggregate"
    )


def test_all_out_of_stock_variants_roll_up_to_out_of_stock() -> None:
    """Rollup precedence only surfaces ``out_of_stock`` when *no* variant is
    buyable — it must not mask a genuinely sold-out catalog as in stock."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="260.00", availability="OutOfStock"),
            _variant_json("SKU-B", "8", price="260.00", availability="OutOfStock"),
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("availability", "variants"),
    )
    assert result.records[0].get("availability") == "out_of_stock"


def test_partial_variant_pricing_publishes_bounded_range_not_a_fake_aggregate() -> None:
    """Slice 3 policy: when only a subset of variants are priced, publish a
    documented bounded ``price_min``/``price_max`` range — never a single value
    pretending the partial coverage is a complete aggregate."""
    variants = ", ".join(
        (
            _variant_json("SKU-A", "7", price="150.00"),
            _variant_json("SKU-B", "8", price="250.00"),
            _variant_json("SKU-C", "9"),  # unpriced -> catalog is incomplete
        )
    )
    result = _extract(
        "ecommerce_detail",
        _variant_group_html(variants=variants),
        "https://shop.test/products/norvan",
        requested_fields=("price", "variants"),
    )
    record = result.records[0]
    # No default variant identified -> no single parent display price fabricated.
    assert record.get("price") is None
    # But the verified priced subset is surfaced as an explicit bounded range.
    assert record.get("price_min") == "150.00"
    assert record.get("price_max") == "250.00"
    assert record["_lineage"]["price_min"]["rule_id"] == "bounded_variant_price_range"
