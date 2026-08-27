from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.connectors.amazon_adapter import AmazonAdapter
from app.crawl.pipeline import record_extraction_stage
from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs


AMAZON_URL = (
    "https://www.amazon.com/evga-geforce-rtx-3090/dp/B08J5F3G18/"
    "ref=pd_ci_mcx_mh_mcx_views_2_image?th=1"
)
AMAZON_HTML = """
<html><body>
  <span id="productTitle">EVGA GeForce RTX 3090</span>
  <span class="a-price"><span class="a-offscreen">$1,499.99</span></span>
  <a id="bylineInfo">Visit the EVGA Store</a>
  <div id="availability"><span>In Stock.</span></div>
  <div id="wayfinding-breadcrumbs_feature_div"><ul><li>Graphics Cards</li></ul></div>
  <img id="landingImage"
       data-old-hires="https://m.media-amazon.com/images/I/71tLsSyLUZL._SX700_.jpg">
  <div id="feature-bullets"><ul>
    <li><span class="a-list-item">24GB GDDR6X memory</span></li>
    <li><span class="a-list-item">Triple-fan cooling</span></li>
  </ul></div>
  <div id="productDescription"><p>Flagship graphics card for 4K gaming.</p></div>
  <table id="productDetails_techSpec_section_1">
    <tr><th>ASIN</th><td>B08J5F3G18</td></tr>
    <tr><th>Item model number</th><td>24G-P5-3987-KR</td></tr>
    <tr><th>UPC</th><td>843368067763</td></tr>
  </table>
</body></html>
"""


@pytest.mark.asyncio
async def test_amazon_adapter_feeds_authoritative_extraction_evidence() -> None:
    adapter_result = await AmazonAdapter().extract(
        AMAZON_URL,
        AMAZON_HTML,
        "ecommerce_detail",
    )

    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            AMAZON_HTML,
            AMAZON_URL,
            requested_fields=(
                "title",
                "url",
                "brand",
                "description",
                "image_url",
                "price",
                "currency",
                "availability",
                "sku",
                "mpn",
            ),
            artifacts={"adapter_artifacts": adapter_result.artifacts},
        )
    )

    assert result.verdict == "success"
    record = result.records[0]
    expected = {
        "availability": "in_stock",
        "brand": "EVGA",
        "currency": "USD",
        "description": "Flagship graphics card for 4K gaming.",
        "image_url": "https://m.media-amazon.com/images/I/71tLsSyLUZL.jpg",
        "mpn": "24G-P5-3987-KR",
        "price": "1499.99",
        "sku": "B08J5F3G18",
        "title": "EVGA GeForce RTX 3090",
        "url": AMAZON_URL,
    }
    assert {key: record.get(key) for key in expected} == expected
    assert {
        row.fact_type for row in result.evidence if row.collector_id == "adapter"
    }.issuperset({"product.brand", "product.description", "offer.price"})


@pytest.mark.asyncio
async def test_amazon_shell_produces_no_adapter_artifact() -> None:
    result = await AmazonAdapter().extract(
        AMAZON_URL,
        "<html><head><title>Amazon.com</title></head><body></body></html>",
        "ecommerce_detail",
    )

    assert result.artifacts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "display_price", "expected_currency"),
    (
        ("https://www.amazon.de/dp/B08J5F3G18", "€1.299,99", "EUR"),
        ("https://www.amazon.com.br/dp/B08J5F3G18", "R$ 1.299,99", "BRL"),
    ),
)
async def test_amazon_adapter_preserves_localized_decimal_price(
    url: str, display_price: str, expected_currency: str
) -> None:
    html = AMAZON_HTML.replace("$1,499.99", display_price)
    adapter_result = await AmazonAdapter().extract(url, html, "ecommerce_detail")
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        url,
        artifacts={"adapter_artifacts": adapter_result.artifacts},
    )

    assert adapter_result.records[0]["price"] == display_price
    assert adapter_result.records[0]["currency"] == expected_currency
    adapter_ref = next(
        ref for ref in request.capture.artifacts if ref.artifact_type == "adapter_json"
    )
    assert adapter_ref.metadata == {
        "source_type": "amazon_adapter",
        "adapter_name": "amazon",
    }
    record = extract(request).records[0]
    assert record["price"] == "1299.99"
    assert record["currency"] == expected_currency


@pytest.mark.asyncio
async def test_record_stage_populates_amazon_adapter_artifacts() -> None:
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=1,
            url=AMAZON_URL,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=AMAZON_URL,
        html=AMAZON_HTML,
        method="browser",
        status_code=200,
    )
    context = SimpleNamespace(
        run=SimpleNamespace(id=1),
        surface="ecommerce_detail",
        config=SimpleNamespace(proxy_list=[]),
    )

    await record_extraction_stage._populate_adapter_artifacts(context, acquisition)

    assert acquisition.adapter_name == "amazon"
    assert acquisition.adapter_source_type == "amazon_adapter"
    assert len(acquisition.artifacts["adapter_artifacts"]) == 1
