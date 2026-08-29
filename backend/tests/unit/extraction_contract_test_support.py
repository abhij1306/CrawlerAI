from tests.unit.extraction_pipeline_test_support import _extract

from app.extraction.engine import _trust_state

import json

from app.extraction import adapters, cascade

from app.extraction.contracts import CollectorOutcome

from app.extraction.surfaces import surface_spec

_DETAIL_HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trail Runner",
  "brand": {"@type": "Brand", "name": "ExampleCo"},
  "sku": "TR-9",
  "url": "https://shop.test/products/trail-runner",
  "image": ["https://shop.test/i/trail-runner.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "149",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  }
}
</script>
</head>
<body><main><h1>Trail Runner</h1><span class="price">$149</span></main></body>
</html>
"""

_DETAIL_URL = "https://shop.test/products/trail-runner"

_DOM_ONLY_DETAIL_HTML = """
<html>
<body><main>
<h1>Canyon Pack</h1>
<span class="price">$88</span>
<img src="https://shop.test/i/canyon.jpg" alt="Canyon Pack">
</main></body>
</html>
"""

_DOM_ONLY_URL = "https://shop.test/products/canyon-pack"


def _detail_result(html: str = _DETAIL_HTML, url: str = _DETAIL_URL):
    return _extract("ecommerce_detail", html, url)


__all__ = [
    "_DETAIL_HTML",
    "_DETAIL_URL",
    "_DOM_ONLY_DETAIL_HTML",
    "_DOM_ONLY_URL",
    "CollectorOutcome",
    "_detail_result",
    "_trust_state",
    "adapters",
    "cascade",
    "json",
    "surface_spec",
]
