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
# Shared HTML-artifact set every listing surface reads: the base rendered
# document plus the rendered listing fragments and visual-element HTML captured
# for JS-rendered boards. Commerce and jobs both read this so a JS-rendered
# listing (whose records only appear after render) is covered on both surfaces.
LISTING_HTML_ARTIFACT_IDS = (
    "html",
    ECOMMERCE_LISTING_FRAGMENT_ARTIFACT_ID,
    ECOMMERCE_LISTING_VISUAL_HTML_ARTIFACT_ID,
)
# Back-compat alias: existing commerce imports keep working unchanged.
ECOMMERCE_LISTING_HTML_ARTIFACT_IDS = LISTING_HTML_ARTIFACT_IDS

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

JOB_LISTING_CARD_SELECTORS: tuple[str, ...] = (
    "[data-job-id]",
    "[data-testid*='job' i]",
    "[class~='job' i]",
    "[class*='job-card' i]",
    "[class*='job-item' i]",
    "[class*='job-post' i]",
    "[class*='posting' i]",
    "article",
    "li",
)

LISTING_CARD_SELECTORS_BY_ROOT_ENTITY = {
    "product": ECOMMERCE_LISTING_CARD_SELECTORS,
    "job": JOB_LISTING_CARD_SELECTORS,
}
LISTING_GENERIC_CARD_SELECTORS_BY_ROOT_ENTITY = {
    "product": ECOMMERCE_LISTING_GENERIC_CARD_SELECTORS,
    "job": frozenset(),
}

JOB_LISTING_TITLE_SELECTORS: tuple[str, ...] = (
    "[data-testid*='title' i]",
    "[class*='title' i]",
    ".body--medium",
    "h2",
    "h3",
    "a[title]",
    "a",
)

JOB_LISTING_URL_SELECTORS: tuple[str, ...] = ("a[href]",)

JOB_LISTING_COMPANY_SELECTORS: tuple[str, ...] = (
    "[data-testid*='company' i]",
    "[class*='company' i]",
)

JOB_LISTING_LOCATION_SELECTORS: tuple[str, ...] = (
    "[data-testid*='location' i]",
    "[class*='location' i]",
    ".body__secondary",
)
