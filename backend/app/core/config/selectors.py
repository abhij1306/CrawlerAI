from __future__ import annotations

ANCHOR_SELECTOR = "a[href]"

CARD_SELECTORS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "[data-component-type='s-search-result']",
        ".s-item",
        "a[href*='/products/']",
        "a[href*='/product/']",
        ".product-card",
        ".product-item",
        ".product-tile",
        ".product-grid-item",
        "[data-testid='product-card']",
        "[data-test-id='product-card']",
        "[data-product-id]",
        "[itemscope][itemtype*='Product']",
        "[class*='productcard' i]",
        "[class*='product-tile']",
        "[class*='search-result-item']",
        "[data-testid*='product' i]",
        "[data-test*='product' i]",
        "[class*='product-card--loaded']",
        "[data-hydrated='true'][class*='product' i]",
    ),
    "article": (
        ".post-card",
        ".post-item",
        ".blog-entry",
        ".news-item",
        "[class*='article-card' i]",
    ),
    "jobs": (
        "[data-qa-id='search-result']",
        ".job_seen_beacon",
        ".base-card",
        ".job-card",
        ".job-listing",
        ".job-result",
        ".posting",
        "[data-testid='job-card']",
        ".jobsearch-ResultsList > div",
        "li.jobs-search__results-list-item",
        "li[data-testid='careers-search-result-listing']",
        "div.job_listing",
        "tr.job-row",
        "div[data-job-id]",
        ".opening",
    ),
}

ECOMMERCE_READY_CARD_SELECTORS = CARD_SELECTORS["ecommerce"]

COOKIE_CONSENT_SELECTORS = (
    "button#onetrust-accept-btn-handler",
    "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#truste-consent-button",
    "[data-consent='accept']",
    "[data-consent-action='accept']",
    "[data-accept='true']",
    "[data-testid='cookie-accept']",
    "[data-testid='consent-accept']",
    ".cookie-consent-accept",
    "#cookieConsentAccept",
    ".fc-button.fc-cta-consent",
    ".fc-button.fc-cta-accept",
    "[id*='accept' i][id*='cookie' i]",
    "[class*='accept' i][class*='cookie' i]",
    "[id*='consent' i][id*='accept' i]",
    "[class*='consent' i][class*='accept' i]",
    "[aria-label='Accept Cookies']",
    "[aria-label='Accept all']",
    "button:has-text('Accept All')",
    "button:has-text('Accept Cookies')",
    "button:has-text('I Accept')",
    "button:has-text('Agree')",
)

PAGINATION_SELECTORS = {
    "load_more": (
        "button:has-text('Load More')",
        "button:has-text('Show More')",
        "button:has-text('View All')",
        "button:has-text('See more')",
        "a:has-text('Load More')",
        "a:has-text('Show More')",
        "[data-testid='load-more']",
        "[data-testid*='load-more' i]",
        "[data-test-id*='load-more' i]",
        ".load-more",
    ),
    "next_page": (
        "a[rel='next']",
        "a[aria-label*='next' i]",
        "a[title*='next' i]",
        "a:has-text('Next')",
        "button[aria-label*='next' i]",
    ),
}

LOCATION_INTERSTITIAL_CONTAINER_SELECTORS = (
    "[aria-modal='true'][class*='location' i]",
    "[aria-modal='true'][id*='location' i]",
    "[aria-modal='true'][class*='postal' i]",
    "[aria-modal='true'][id*='postal' i]",
    "[aria-modal='true'][class*='zip' i]",
    "[aria-modal='true'][id*='zip' i]",
    "[role='dialog'][class*='location' i]",
    "[role='dialog'][id*='location' i]",
    "[role='dialog'][class*='postal' i]",
    "[role='dialog'][id*='postal' i]",
    "[role='dialog'][class*='zip' i]",
    "[role='dialog'][id*='zip' i]",
    ".modal[class*='location' i]",
    ".modal[id*='location' i]",
    ".overlay[class*='location' i]",
    ".overlay[id*='location' i]",
)

LOCATION_INTERSTITIAL_DISMISS_SELECTORS = (
    "button[aria-label='Close']",
    "button[aria-label='close']",
    "[role='button'][aria-label='Close']",
    "[role='button'][aria-label='close']",
)

LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS = (
    "not now",
    "maybe later",
    "continue",
    "continue without location",
    "skip",
    "no thanks",
)

LOCATION_INTERSTITIAL_TEXT_TOKENS = (
    "choose your location",
    "select your location",
    "set your location",
    "enter your zip",
    "enter zip code",
    "zip code",
    "postal code",
    "use my location",
    "deliver to",
    "store location",
)

CLOUDFLARE_TURNSTILE_SELECTORS = (
    'iframe[src*="challenges.cloudflare.com"]',
    "div.cf-turnstile",
    "#cf-turnstile",
)

LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS = (
    "header",
    "footer",
    "nav",
    '[role="navigation"]',
    '[role="banner"]',
    '[role="contentinfo"]',
    "dialog",
    '[role="dialog"]',
    "aside",
)

LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS = (
    "article",
    "li",
    "section",
    '[role="listitem"]',
    '[data-testid*="product" i]',
    '[class*="product" i]',
    '[class*="card" i]',
    '[class*="tile" i]',
    '[class*="item" i]',
    '[class*="result" i]',
)

LISTING_VISUAL_CAPTURE_SELECTORS = (
    "a[href]",
    "img[src]",
    "h1",
    "h2",
    "h3",
    "h4",
    '[itemprop="name"]',
    '[class*="price" i]',
    '[data-testid*="price" i]',
    '[aria-label*="price" i]',
    '[class*="title" i]',
    '[data-testid*="title" i]',
    '[data-testid*="name" i]',
)

LISTING_FIELD_SELECTORS: dict[str, tuple[str, ...]] = {
    "title": (
        "[itemprop='name']",
        "[class*='title']",
        "[data-testid*='title']",
        "[data-testid*='name']",
        "a[href]",
    ),
    "price": (
        "[itemprop='price']",
        "[class*='price']",
        "[data-testid*='price']",
        "[data-price]",
    ),
    "image_url": (
        "[itemprop='image']",
        "img[src]",
        "[class*='image']",
        "[data-testid*='image']",
    ),
}

__all__ = [
    "ANCHOR_SELECTOR",
    "CARD_SELECTORS",
    "CLOUDFLARE_TURNSTILE_SELECTORS",
    "COOKIE_CONSENT_SELECTORS",
    "ECOMMERCE_READY_CARD_SELECTORS",
    "LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS",
    "LISTING_FIELD_SELECTORS",
    "LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS",
    "LISTING_VISUAL_CAPTURE_SELECTORS",
    "LOCATION_INTERSTITIAL_CONTAINER_SELECTORS",
    "LOCATION_INTERSTITIAL_DISMISS_SELECTORS",
    "LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS",
    "LOCATION_INTERSTITIAL_TEXT_TOKENS",
    "PAGINATION_SELECTORS",
]
