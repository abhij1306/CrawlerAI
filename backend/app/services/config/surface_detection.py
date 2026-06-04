from __future__ import annotations

AUTO_SURFACE = "auto"

PUBLIC_SURFACE_AUTO = "auto"
PUBLIC_SURFACE_ECOMMERCE = "ecommerce"
PUBLIC_SURFACE_CONTENT = "content"
PUBLIC_SURFACE_ARTICLE = "article"
PUBLIC_SURFACE_FORUM_THREAD = "forum_thread"

PUBLIC_TO_DETAIL_SURFACE = {
    PUBLIC_SURFACE_ECOMMERCE: "ecommerce_detail",
    PUBLIC_SURFACE_CONTENT: "content_detail",
    PUBLIC_SURFACE_ARTICLE: "article_detail",
    PUBLIC_SURFACE_FORUM_THREAD: "forum_detail",
}

PUBLIC_TO_LISTING_SURFACE = {
    PUBLIC_SURFACE_ECOMMERCE: "ecommerce_listing",
    PUBLIC_SURFACE_CONTENT: "content_listing",
    PUBLIC_SURFACE_ARTICLE: "article_listing",
}

PUBLIC_SUPPORTED_SURFACES = frozenset(
    {
        PUBLIC_SURFACE_AUTO,
        PUBLIC_SURFACE_ECOMMERCE,
        PUBLIC_SURFACE_CONTENT,
        PUBLIC_SURFACE_ARTICLE,
        PUBLIC_SURFACE_FORUM_THREAD,
    }
)

SURFACE_RESOLVER_FORUM_HOST_TOKENS = ("forum", "discuss", "community")
SURFACE_RESOLVER_ARTICLE_HOSTS = frozenset({"codeforces.com"})
SURFACE_RESOLVER_ARTICLE_PATH_TOKENS = (
    "/blog/",
    "/blog/entry/",
    "/article/",
    "/articles/",
    "/news/",
    "/post/",
    "/posts/",
)
SURFACE_RESOLVER_FORUM_PATH_TOKENS = (
    "/thread/",
    "/threads/",
    "/forum/",
    "/forums/",
    "/discussion/",
    "/discussions/",
    "/questions/",
    "/answers/",
    "/comments/",
)
SURFACE_RESOLVER_ECOMMERCE_DETAIL_PATH_TOKENS = (
    "/product/",
    "/products/",
    "/p/",
    "/item/",
    "/dp/",
)
SURFACE_RESOLVER_ECOMMERCE_LISTING_PATH_TOKENS = (
    "/collections/",
    "/collection/",
    "/category/",
    "/categories/",
    "/search",
    "/shop/",
)
SURFACE_RESOLVER_ECOMMERCE_LISTING_PATH_SEGMENTS = (
    "accessories",
    "apparel",
    "bags",
    "beauty",
    "boys",
    "clothing",
    "dresses",
    "gifts",
    "girls",
    "home",
    "jackets",
    "jeans",
    "kids",
    "men",
    "mens",
    "new-arrivals",
    "pants",
    "sale",
    "shirts",
    "shoes",
    "shorts",
    "sweaters",
    "tops",
    "women",
    "womens",
)
SURFACE_RESOLVER_ECOMMERCE_DETAIL_SKU_HTML_PATTERN = (
    r"(?:^|/)[a-z0-9][a-z0-9-]*-[a-z0-9]*\d[a-z0-9]{5,}\.html$"
)
SURFACE_RESOLVER_ECOMMERCE_DETAIL_HTML_MIN_HYPHENS = 3
SURFACE_RESOLVER_ECOMMERCE_DETAIL_HTML_EXTENSION = ".html"
SURFACE_RESOLVER_JOB_PATH_TOKENS = (
    "/job/",
    "/jobs/",
    "/careers/",
    "/positions/",
    "/openings/",
)

SURFACE_RESOLVER_HTML_TYPES = {
    "product": "ecommerce_detail",
    "jobposting": "job_detail",
    "article": "article_detail",
    "newsarticle": "article_detail",
    "blogposting": "article_detail",
    "discussionforumposting": "forum_detail",
}

SURFACE_RESOLVER_LOW_CONFIDENCE = 0.4
SURFACE_RESOLVER_MEDIUM_CONFIDENCE = 0.7
SURFACE_RESOLVER_HIGH_CONFIDENCE = 0.9
