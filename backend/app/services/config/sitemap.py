from __future__ import annotations

SITEMAP_DEFAULT_FILTER_KEYWORD = ""
SITEMAP_DEFAULT_MAX_URLS = 500
PLAYGROUND_CATEGORY_DEFAULT_LIMIT = 10
PLAYGROUND_CATEGORY_MAX_LIMIT = 50
PLAYGROUND_CATEGORY_PER_INPUT_TIMEOUT_SECONDS = 20
SITEMAP_FETCH_TIMEOUT_SECONDS = 15
SITEMAP_FETCH_RETRY_ATTEMPTS = 2
SITEMAP_FETCH_RETRY_DELAY_SECONDS = 0.5
SITEMAP_FETCH_RETRY_STATUS_CODES = (429, 502, 503, 504)
SITEMAP_FETCH_MAX_REDIRECTS = 5
SITEMAP_USER_AGENT = "Mozilla/5.0 (compatible; CrawlwiseBot/1.0)"
# Path tokens that signal a page is not a category/listing/detail candidate
# (account, auth, support, legal, transactional flows, on-page search). These
# are surface-agnostic — we deliberately do NOT exclude /blog or /news here
# because content/article surfaces use the same homepage fallback path and
# blog/news hubs are valid listing targets for those surfaces.
SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_PATH_TOKENS = (
    "/account",
    "/apps",
    "/auth",
    "/cart",
    "/checkout",
    "/contact",
    "/faq",
    "/faqs",
    "/help",
    "/login",
    "/logout",
    "/myorders",
    "/order",
    "/payment",
    "/policies",
    "/policy",
    "/privacy",
    "/refund",
    "/register",
    "/returns",
    "/search",
    "/shipping",
    "/signin",
    "/signup",
    "/support",
    "/terms",
    "/store",
    "/store-locator",
    "/stores",
    "/wishlist",
)
SITEMAP_HOMEPAGE_FALLBACK_EXCLUDED_EXTENSIONS = (
    ".avif",
    ".css",
    ".gif",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".webp",
    ".xml",
    ".zip",
)
SITEMAP_CATEGORY_PATH_TOKENS = (
    "/c/",
    "/cat/",
    "/category/",
    "/categories/",
    "/collection/",
    "/collections/",
    "/department/",
    "/departments/",
    "/shop/",
    "/w/",
)
SITEMAP_CATEGORY_EXCLUDED_PATH_TOKENS = (
    "/address",
    "/article/",
    "/articles/",
    "/blog/",
    "/blogs/",
    "/cart",
    "/change-location",
    "/checkout",
    "/dp/",
    "/item/",
    "/my-order",
    "/news/",
    "/order",
    "/page/",
    "/pages/",
    "/p/",
    "/policy",
    "/policies",
    "/post/",
    "/posts/",
    "/product/",
    "/products/",
    "/saved-item",
    "/search",
    "/store",
    "/wishlist",
)
SITEMAP_CATEGORY_ANCHOR_TEXT_TOKENS = (
    "accessories",
    "apparel",
    "bags",
    "beauty",
    "boys",
    "clothing",
    "collections",
    "dresses",
    "girls",
    "home",
    "jackets",
    "jeans",
    "kids",
    "men",
    "new arrivals",
    "pants",
    "sale",
    "shirts",
    "shoes",
    "shorts",
    "sweaters",
    "tops",
    "women",
)
SITEMAP_CATEGORY_ANCHOR_TEXT_EXCLUDED_TOKENS = (
    "account",
    "address",
    "app",
    "bag",
    "cart",
    "country",
    "customer service",
    "help",
    "language",
    "location",
    "login",
    "order",
    "payment",
    "privacy",
    "saved",
    "sign in",
    "store",
    "support",
    "terms",
    "wishlist",
)
# Long department/category labels on retail navs ("Home & Kitchen Storage
# & Organization") routinely exceed 6 words. Use 10 to keep real categories
# while still rejecting obvious sentences/marketing copy.
SITEMAP_HOMEPAGE_FALLBACK_MAX_LINK_TEXT_WORDS = 10
SITEMAP_HOMEPAGE_FALLBACK_MAX_ANCHORS = 500
SITEMAP_HOMEPAGE_FALLBACK_MAX_VALIDATIONS = 100
SITEMAP_HOMEPAGE_CATEGORY_PATH_SCORE_BOOST = 20

# Threshold below which a sitemap result is considered "thin" — when the
# real sitemap returns fewer usable URLs than this and homepage fallback is
# allowed, also harvest the homepage and merge the two ranked sets. Keeps
# coverage on sites that publish a token sitemap (policy pages only).
SITEMAP_THIN_RESULT_THRESHOLD = 5
