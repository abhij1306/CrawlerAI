from __future__ import annotations

import pytest

from app.services.adapters.myntra import MyntraAdapter


@pytest.mark.asyncio
@pytest.mark.component
async def test_myntra_adapter_extracts_listing_cards_from_dom() -> None:
    html = """
    <html>
      <body>
        <script>
          window.__myx = {
            "searchData": {
              "results": {
                "products": [
                  {
                    "productId": 20510856,
                    "productName": "Mamaearth Vitamin C Daily Glow Face Cream",
                    "brand": "Mamaearth",
                    "landingPageUrl": "day-cream/mamaearth/mamaearth-vitamin-c-daily-glow-face-cream-with-vitc--turmeric-for-skin-illumination-150g/20510856/buy",
                    "searchImage": "https://assets.myntassets.com/a.jpg",
                    "price": 351,
                    "mrp": 399,
                    "sizes": "100-150 ML",
                    "rating": 4.3,
                    "ratingCount": 11900
                  },
                  {
                    "productId": 49887766,
                    "productName": "Plum Rice Water & Niacinamide Gel Cream",
                    "brand": "Plum",
                    "landingPageUrl": "face-moisturiser/plum/plum-rice-water--niacinamide-gel-cream/49887766/buy",
                    "searchImage": "https://assets.myntassets.com/plum.jpg",
                    "price": 299,
                    "mrp": 349,
                    "sizes": "50 g",
                    "rating": 4.1,
                    "ratingCount": 800
                  }
                ]
              }
            }
          };
        </script>
        <ul class="results-base">
          <li id="20510856" class="product-base">
            <a href="day-cream/mamaearth/mamaearth-vitamin-c-daily-glow-face-cream-with-vitc--turmeric-for-skin-illumination-150g/20510856/buy">
              <div class="product-productMetaInfo">
                <h3 class="product-brand">Mamaearth</h3>
                <h4 class="product-product">Vit. C Daily Glow Cream 150g</h4>
                <h4 class="product-sizes">Sizes: 100-150 ML</h4>
                <div class="product-price">
                  <span class="product-discountedPrice">Rs. 351</span>
                  <span class="product-strike">Rs. 399</span>
                </div>
              </div>
            </a>
          </li>
          <li id="31145778" class="product-base">
            <a href="day-cream/asaya/asaya-even-evermore-cream-with-alpha-arbutin--ceramides---50g/31145778/buy">
              <div class="product-productMetaInfo">
                <h3 class="product-brand">Asaya</h3>
                <h4 class="product-product">Even Evermore Cream - 50g</h4>
                <h4 class="product-sizes">Sizes: 40-50gm</h4>
                <div class="product-price">
                  <span class="product-discountedPrice">Rs. 449</span>
                  <span class="product-strike">Rs. 599</span>
                </div>
              </div>
            </a>
          </li>
        </ul>
      </body>
    </html>
    """

    adapter = MyntraAdapter()

    result = await adapter.extract(
        "https://www.myntra.com/face-moisturisers",
        html,
        "ecommerce_listing",
    )

    assert len(result.records) == 3
    assert result.records[0]["brand"] == "Mamaearth"
    assert result.records[0]["image_url"] == "https://assets.myntassets.com/a.jpg"
    assert result.records[0]["currency"] == "INR"
    assert result.records[0]["url"].endswith("/20510856/buy")
    assert result.records[1]["title"] == "Even Evermore Cream - 50g"
    assert result.records[1]["currency"] == "INR"
    assert result.records[2]["title"] == "Plum Rice Water & Niacinamide Gel Cream"
    assert result.records[2]["image_url"] == "https://assets.myntassets.com/plum.jpg"
    assert result.records[2]["url"].endswith("/49887766/buy")


@pytest.mark.asyncio
@pytest.mark.component
async def test_myntra_adapter_extracts_listing_records_from_state_without_dom_cards() -> None:
    html = """
    <html>
      <body>
        <script>
          window.__myx = {
            "searchData": {
              "results": {
                "products": [
                  {
                    "productId": 37943174,
                    "productName": "StyleCast x Revolte Men Wide Leg Mid-Rise Light Fade Jeans",
                    "brand": "StyleCast x Revolte",
                    "landingPageUrl": "jeans/stylecast+x+revolte/stylecast-x-revolte-men-wide-leg-mid-rise-light-fade-jeans/37943174/buy",
                    "searchImage": "https://assets.myntassets.com/jeans.jpg",
                    "price": 1439,
                    "mrp": 3999,
                    "sizes": "24,26,28,30,32,34",
                    "rating": 3.55,
                    "ratingCount": 1360,
                    "inventoryInfo": [{"available": true}]
                  }
                ]
              }
            }
          };
        </script>
        <nav>
          <a href="/fwdgenzcollection?f=Categories%3ADresses&rf=Price%3A0.0_600.0_0.0%20TO%20600.0">Dresses Under Rs.599</a>
        </nav>
      </body>
    </html>
    """

    result = await MyntraAdapter().extract(
        "https://www.myntra.com/men-jeans",
        html,
        "ecommerce_listing",
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "StyleCast x Revolte Men Wide Leg Mid-Rise Light Fade Jeans"
    assert result.records[0]["brand"] == "StyleCast x Revolte"
    assert result.records[0]["price"] == "1439"
    assert result.records[0]["currency"] == "INR"
    assert result.records[0]["image_url"] == "https://assets.myntassets.com/jeans.jpg"
    assert result.records[0]["url"].endswith("/37943174/buy")
