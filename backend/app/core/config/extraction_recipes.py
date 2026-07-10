from __future__ import annotations

ECOMMERCE_LISTING_CARD_SELECTORS: tuple[str, ...] = (
    "[data-product-id]",
    "[data-cnstrc-item-id]",
    "[data-cnstrc-item-name]",
    "[data-tile-type='product' i]",
    "[data-testid*='product' i]",
    "[data-test-id='product-card' i]",
    "[test-data-id*='product' i]",
    "[test-dataid*='product' i]",
    "[data-test-data-id*='product' i]",
    "[data-test-dataid*='product' i]",
    "[class~='product']",
    "[class*='product-card' i]",
    "[class*='product-tile' i]",
    "[class*='productitem' i]",
    "[class*='product-item' i]",
    "article",
    "li",
)

ECOMMERCE_LISTING_SCOPE_SELECTORS: tuple[str, ...] = (
    "main",
    "[role='main']",
    "#pageContent",
    ".main-content",
)

ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS = frozenset({"article", "li"})
ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID = "rendered_listing_fragments"
ECOMMERCE_LISTING_VISUAL_ARTIFACT_ID = "listing_visual_elements"
ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID = "listing_visual_html"
ECOMMERCE_LISTING_HTML_ARTIFACT_IDS = (
    "html",
    ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID,
    ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID,
)

ECOMMERCE_LISTING_TITLE_SELECTORS: tuple[str, ...] = (
    "[data-testid*='title' i]",
    "[class*='title' i]",
    "[class*='name' i]",
    "h2",
    "h3",
    "a[title]",
    "a",
)

ECOMMERCE_LISTING_TITLE_ATTRIBUTES: tuple[str, ...] = (
    "title",
    "aria-label",
    "data-cnstrc-item-name",
    "data-product-name",
    "data-item-name",
)

ECOMMERCE_LISTING_URL_SELECTORS: tuple[str, ...] = ("a[href]",)

ECOMMERCE_LISTING_PRICE_SELECTORS: tuple[str, ...] = (
    "[data-price]",
    "[class*='price' i]",
    "[data-testid*='price' i]",
)

ECOMMERCE_LISTING_IMAGE_SELECTORS: tuple[str, ...] = (
    "img[src]",
    "img[data-src]",
    "source[srcset]",
)

JOB_DETAIL_TITLE_SELECTORS: tuple[str, ...] = (
    "h1",
    "[data-testid*='title' i]",
    "[class*='job-title' i]",
)

JOB_DETAIL_COMPANY_SELECTORS: tuple[str, ...] = (
    "[data-testid*='company' i]",
    "[class*='company' i]",
    "[itemprop='hiringOrganization']",
)

JOB_DETAIL_LOCATION_SELECTORS: tuple[str, ...] = (
    "[data-testid*='location' i]",
    "[class*='location' i]",
    "[itemprop='jobLocation']",
)

JOB_DETAIL_DESCRIPTION_SELECTORS: tuple[str, ...] = (
    "[data-testid*='description' i]",
    "[class*='description' i]",
    "[itemprop='description']",
    "main",
)

JOB_DETAIL_APPLY_SELECTORS: tuple[str, ...] = (
    "a[href*='apply' i]",
    "a[href*='application' i]",
)
