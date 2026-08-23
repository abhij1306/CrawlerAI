from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *


@pytest.mark.regression
def test_require_explicit_surface_rejects_missing_surface() -> None:
    assert require_explicit_surface("job_listing") == "job_listing"
    with pytest.raises(ValueError, match="surface is required"):
        require_explicit_surface()


@pytest.mark.regression
def test_parse_test_sites_markdown_skips_untyped_tail_urls(tmp_path: Path) -> None:
    path = tmp_path / "TEST_SITES.md"
    path.write_text(
        "ignore\nhttps://example.com/careers\nnot a url\nhttps://shop.example.com/collections\n",
        encoding="utf-8",
    )
    assert parse_test_sites_markdown(path, start_line=2) == []


@pytest.mark.regression
def test_parse_test_sites_markdown_reads_urls_from_markdown_tables(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "TEST_SITES.md"
    fixture.write_text(
        "\n".join(
            [
                "| Name | URL | Type |",
                "| --- | --- | --- |",
                "| Listing | https://web-scraping.dev/products | Listing |",
                "| Detail | https://web-scraping.dev/product/1 | Detail |",
                "| Tool | https://practicesoftwaretesting.com/product/01HB | Detail |",
            ]
        ),
        encoding="utf-8",
    )

    rows = parse_test_sites_markdown(fixture, start_line=1)

    assert any(
        row["url"] == "https://web-scraping.dev/products"
        and row["surface"] == "ecommerce_listing"
        for row in rows
    )
    assert any(
        row["url"] == "https://web-scraping.dev/product/1"
        and row["surface"] == "ecommerce_detail"
        for row in rows
    )
    assert any(
        row["url"] == "https://practicesoftwaretesting.com/product/01HB"
        and row["surface"] == "ecommerce_detail"
        for row in rows
    )


@pytest.mark.regression
def test_build_explicit_sites_preserves_explicit_surface_order() -> None:
    rows = build_explicit_sites(
        [
            "https://example.com/search?q=widgets",
            "https://example.com/products/widget-prime",
        ],
        explicit_surfaces=["ecommerce_listing", "ecommerce_detail"],
    )

    assert rows == [
        {
            "name": "https://example.com/search?q=widgets",
            "url": "https://example.com/search?q=widgets",
            "surface": "ecommerce_listing",
        },
        {
            "name": "https://example.com/products/widget-prime",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
        },
    ]


@pytest.mark.regression
def test_build_explicit_sites_rejects_mismatched_surface_count() -> None:
    with pytest.raises(ValueError, match="surface counts must match"):
        build_explicit_sites(
            ["https://example.com/products/widget-prime"],
            explicit_surfaces=["ecommerce_detail", "ecommerce_listing"],
        )


@pytest.mark.regression
def test_unavailable_configured_adapters_uses_config_without_legacy_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness_support,
        "configured_adapter_names",
        lambda: ("bullhorn", "icims"),
    )

    assert harness_support.unavailable_configured_adapters() == {
        "bullhorn",
        "icims",
    }


@pytest.mark.regression
def test_load_site_set_preserves_curated_surface_and_bucket(tmp_path: Path) -> None:
    manifest = tmp_path / "sites.json"
    manifest.write_text(
        """
        {
          "site_sets": {
            "commerce": {
              "sites": [
                {
                  "name": "Catalog",
                  "url": "https://example.com/search?q=widgets",
                  "surface": "ecommerce_listing",
                  "bucket": "must_pass",
                  "expected_failure_modes": ["success"],
                  "artifact_run_id": 77,
                  "seed_failure_mode": "listing_chrome_noise",
                  "quality_expectations": {"require_price": true}
                }
              ]
            }
          }
        }
        """,
        encoding="utf-8",
    )

    rows = load_site_set(manifest, site_set_name="commerce")

    assert rows == [
        {
            "name": "Catalog",
            "url": "https://example.com/search?q=widgets",
            "surface": "ecommerce_listing",
            "bucket": "must_pass",
            "expected_failure_modes": ["success"],
            "artifact_run_id": 77,
            "seed_failure_mode": "listing_chrome_noise",
            "quality_expectations": {"require_price": True},
        }
    ]


@pytest.mark.regression
def test_load_site_set_reports_json_path_on_decode_error(tmp_path: Path) -> None:
    manifest = tmp_path / "bad-sites.json"
    manifest.write_text("{ invalid json", encoding="utf-8")

    with pytest.raises(ValueError, match="bad-sites.json"):
        load_site_set(manifest, site_set_name="commerce")


@pytest.mark.regression
def test_load_site_set_merges_defaults(tmp_path: Path) -> None:
    manifest = tmp_path / "sites.json"
    manifest.write_text(
        """
        {
          "name": "commerce",
          "defaults": {
            "surface": "ecommerce_detail",
            "bucket": "commerce_extended",
            "gate": "soft",
            "quality_expectations": {"require_identity": true, "require_price": true}
          },
          "sites": [
            {
              "name": "Product",
              "url": "https://example.com/products/widget",
              "quality_expectations": {"require_price": false}
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = load_site_set(manifest, site_set_name="commerce")

    assert rows == [
        {
            "name": "Product",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "bucket": "commerce_extended",
            "expected_failure_modes": [],
            "artifact_run_id": None,
            "seed_failure_mode": None,
            "quality_expectations": {
                "require_identity": True,
                "require_price": False,
            },
            "gate": "soft",
        }
    ]
