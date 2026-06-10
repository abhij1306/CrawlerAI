from __future__ import annotations

PAGE_AUDIT_JOB_STATUS_QUEUED = "queued"
PAGE_AUDIT_JOB_STATUS_RUNNING = "running"
PAGE_AUDIT_JOB_STATUS_COMPLETE = "complete"
PAGE_AUDIT_JOB_STATUS_FAILED = "failed"

PAGE_AUDIT_CONTEXT_AUTO = "auto"
PAGE_AUDIT_CONTEXT_GENERIC = "generic"
PAGE_AUDIT_CONTEXT_ECOMMERCE = "ecommerce"
PAGE_AUDIT_ALLOWED_CONTEXTS = (
    PAGE_AUDIT_CONTEXT_AUTO,
    PAGE_AUDIT_CONTEXT_GENERIC,
    PAGE_AUDIT_CONTEXT_ECOMMERCE,
)

PAGE_AUDIT_HTTP_TIMEOUT_SECONDS = 15.0
PAGE_AUDIT_BROWSER_TIMEOUT_SECONDS = 30.0
PAGE_AUDIT_DEFAULT_REPORT_FORMATS = ("json", "markdown")
PAGE_AUDIT_SOURCE_FETCH_MODE = "http_only"
PAGE_AUDIT_BROWSER_FETCH_MODE = "browser_only"
PAGE_AUDIT_BROWSER_REASON = "page_audit_render"
PAGE_AUDIT_SURFACE = "content_detail"

TITLE_MIN_CHARS = 30
TITLE_MAX_CHARS = 60
META_DESCRIPTION_MIN_CHARS = 100
META_DESCRIPTION_MAX_CHARS = 160
MAX_EXTERNAL_SCRIPT_COUNT = 15
MAX_ANALYTICS_STACK_COUNT = 2
MAX_SRCSET_ENTRIES = 10
MAX_INLINE_STYLE_BYTES = 50_000
MAX_FONT_FAMILIES = 2
ABOVE_FOLD_IMAGE_SAMPLE_SIZE = 5
DOM_ONLY_TEXT_SAMPLE_SIZE = 10
DOM_ONLY_LINK_SAMPLE_SIZE = 20

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"
SEVERITY_WEIGHTS = {
    SEVERITY_CRITICAL: 4,
    SEVERITY_HIGH: 3,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 1,
}

DATA_SOURCE_SOURCE = "source"
DATA_SOURCE_DOM = "dom"
DATA_SOURCE_DIFF = "diff"

CATEGORY_SEO = "seo"
CATEGORY_PERFORMANCE = "performance_indicators"
CATEGORY_STRUCTURED_DATA = "structured_data"
CATEGORY_ACCESSIBILITY = "accessibility"
CATEGORY_ECOMMERCE = "ecommerce_readiness"

LCP_CANDIDATE_SELECTORS = (
    "h1",
    "img[fetchpriority='high']",
    "[class*='hero' i] img",
    "[class*='banner' i] img",
    "video[poster]",
    "img",
)
PRICE_SELECTORS = (
    "[class*='price' i]",
    "[itemprop='price']",
    "meta[itemprop='price']",
)
ADD_TO_CART_SELECTORS = (
    "button[class*='cart' i]",
    "button[class*='add' i]",
    "[data-testid*='add-to-cart' i]",
)
VARIANT_SELECTORS = (
    "select[name*='variant' i]",
    "[data-variant]",
    "[class*='variant' i]",
)
OUT_OF_STOCK_SELECTORS = (
    "[class*='sold-out' i]",
    "[class*='out-of-stock' i]",
)
BREADCRUMB_SELECTORS = (
    "nav[aria-label*='breadcrumb' i]",
    "[class*='breadcrumb' i]",
)
REVIEW_COUNT_SELECTORS = (
    "[itemprop='reviewCount']",
    "[class*='review-count' i]",
)

ANALYTICS_SIGNALS = (
    "googletagmanager.com/gtm.js",
    "googletagmanager.com/gtag/js",
    "google-analytics.com",
    "clarity.ms",
    "hotjar.com",
)
AB_TEST_SIGNALS = ("vwo", "optimizely", "abtasty", "ab-tasty")
CHAT_SIGNALS = ("intercom", "drift", "crisp", "hubspot")
SUSPICIOUS_IMAGE_HOSTS = ("drive.google.com", "dropbox.com", "dropboxusercontent.com")
FRAMEWORK_SIGNALS = {
    "next.js": ("/_next/", "__NEXT_DATA__"),
    "nuxt": ("/_nuxt/", "__NUXT__"),
    "gatsby": ("/page-data/", "gatsby"),
    "astro": ("astro-island", "astro:"),
    "vue": ("__vue_app__", "/vue."),
    "react": ("__react", "react-dom"),
}

CHECK_COPY = {
    "title_exists": ("Title tag exists", "Add one non-empty title tag."),
    "title_length": ("Title length is 30-60 characters", "Keep the title between 30 and 60 characters."),
    "meta_description_exists": ("Meta description exists", "Add a meta description."),
    "meta_description_length": ("Meta description length is 100-160 characters", "Keep the meta description between 100 and 160 characters."),
    "h1_count": ("Page has exactly one H1", "Use exactly one H1."),
    "h1_non_empty": ("H1 is non-empty", "Add useful text to the H1."),
    "canonical_exists": ("Canonical tag exists", "Add a canonical link."),
    "canonical_matches_url": ("Canonical matches page URL", "Point the canonical link at the final page URL."),
    "lang_attribute": ("HTML lang attribute exists", "Add a valid language code to html[lang]."),
    "robots_indexable": ("Robots meta allows indexing", "Remove noindex from the robots meta tag."),
    "viewport_mobile": ("Viewport declares device width", "Add width=device-width to the viewport meta tag."),
    "og_title": ("Open Graph title exists", "Add og:title."),
    "og_description": ("Open Graph description exists", "Add og:description."),
    "og_image": ("Open Graph image exists", "Add og:image."),
    "og_url": ("Open Graph URL exists and matches canonical", "Add og:url and align it with the canonical URL."),
    "twitter_card": ("Twitter card exists", "Add twitter:card."),
    "twitter_image": ("Twitter image exists", "Add twitter:image."),
    "jsonld_present": ("JSON-LD exists", "Add a JSON-LD block."),
    "jsonld_parseable": ("JSON-LD parses", "Fix malformed JSON-LD."),
    "schema_types_detected": ("Schema types are detected", "Declare schema.org @type values."),
    "schema_organization_present": ("Organization schema exists", "Add Organization schema on the homepage."),
    "schema_breadcrumb_present": ("Breadcrumb schema exists", "Add BreadcrumbList schema on inner pages."),
    "schema_product_present": ("Product schema exists", "Add Product schema on product pages."),
    "schema_review_present": ("Review schema exists", "Add Review or AggregateRating schema when reviews are shown."),
    "lcp_candidate_present": ("LCP candidate is identifiable", "Expose a clear hero image, heading, or video poster at load."),
    "lcp_candidate_visible": ("LCP candidate is visible", "Do not hide the likely LCP element at load."),
    "lcp_candidate_in_source": ("LCP candidate exists in source HTML", "Server-render the likely LCP element."),
    "lcp_candidate_lazy_loaded": ("LCP candidate is not lazy-loaded", "Remove loading=lazy from the likely LCP image."),
    "above_fold_images_eager": ("Above-fold images are not lazy-loaded", "Do not lazy-load images in the first viewport."),
    "hero_image_priority": ("Hero image has high fetch priority", "Set fetchpriority=high on the primary hero image."),
    "images_have_alt": ("Images have alt text", "Add meaningful alt text, or an intentional empty alt for decorative images."),
    "images_have_dimensions": ("Images have width and height", "Set image width and height to reduce layout shift."),
    "image_origins_reliable": ("Images avoid file-sharing origins", "Serve production images from the site or an image CDN."),
    "srcset_size_reasonable": ("Srcset sizes are bounded", "Reduce oversized srcset candidate lists."),
    "external_script_count": ("External script count is bounded", "Reduce third-party and external scripts."),
    "render_blocking_scripts": ("Head scripts do not block rendering", "Use async, defer, or modules for non-critical scripts."),
    "analytics_stack_bounded": ("Analytics stack is bounded", "Remove redundant analytics tools."),
    "gtm_not_redundant": ("GTM and gtag are not both loaded", "Consolidate Google analytics loading."),
    "ab_testing_tools_absent": ("No A/B testing payload detected", "Review the performance cost of A/B testing scripts."),
    "chat_widgets_absent": ("No chat widget payload detected", "Delay or remove chat widgets that affect rendering."),
    "framework_detected": ("Framework signals recorded", "No action required."),
    "forms_have_action": ("Forms declare an action", "Add a form action or document the intentional JavaScript-only flow."),
    "forms_have_csrf": ("Forms include a CSRF token", "Add CSRF protection to state-changing forms."),
    "inputs_have_labels": ("Inputs have accessible labels", "Associate labels or aria-label with form controls."),
    "password_autocomplete_allowed": ("Password fields allow autocomplete", "Use an appropriate password autocomplete value."),
    "sensitive_forms_not_get": ("Sensitive forms do not use GET", "Submit sensitive values with POST."),
    "anchor_targets_exist": ("Fragment links target existing IDs", "Add the target ID or fix the fragment link."),
    "external_blank_links_secure": ("New-tab external links are protected", "Add rel=noopener noreferrer."),
    "duplicate_ids_absent": ("DOM IDs are unique", "Remove duplicate ID attributes."),
    "single_canonical": ("Only one canonical tag exists", "Keep one canonical link."),
    "internal_nofollow_absent": ("Internal links are not unexpectedly nofollow", "Remove nofollow from important internal links."),
    "critical_fonts_preloaded": ("Critical fonts are preloaded", "Preload critical self-hosted fonts."),
    "font_preloads_crossorigin": ("Font preloads use crossorigin", "Add crossorigin to font preload links."),
    "google_fonts_nonblocking": ("Google Fonts avoid blocking load", "Preconnect or preload Google Fonts."),
    "font_family_count": ("Font family count is bounded", "Use at most two font families."),
    "stylesheets_in_head": ("Stylesheets are not placed in body", "Move stylesheet links into head."),
    "inline_style_size": ("Inline style payload is bounded", "Reduce inline CSS below 50 KB."),
    "single_title": ("Only one title tag exists", "Keep one title tag."),
    "base_tag_absent": ("No base tag changes URL resolution", "Remove the base tag unless it is strictly required."),
    "content_present_in_source": ("Rendered content is present in source HTML", "Server-render important visible content."),
    "links_present_in_source": ("Rendered links are present in source HTML", "Server-render important navigation links."),
    "h1_present_in_source": ("Rendered H1 is present in source HTML", "Server-render the H1."),
    "schema_present_in_source": ("Rendered schema is present in source HTML", "Emit JSON-LD in the initial response."),
    "lcp_candidate_matches_source": ("LCP candidate is consistent between source and DOM", "Server-render the same primary content users see."),
    "ecommerce_price_present": ("Product price is present", "Expose a product price in visible or structured markup."),
    "ecommerce_product_schema_present": ("Product schema is present", "Add schema.org Product JSON-LD."),
    "ecommerce_offers_complete": ("Product offers include price and availability", "Add price and availability to Product offers."),
    "ecommerce_add_to_cart_present": ("Add-to-cart control is present", "Expose a clear add-to-cart control."),
    "ecommerce_variants_detected": ("Variant controls are detected", "Expose variant controls when the product has options."),
    "ecommerce_stock_signal_present": ("Stock state is detectable", "Expose availability in DOM or schema."),
    "ecommerce_breadcrumbs_present": ("Breadcrumbs are present", "Add product breadcrumbs."),
    "ecommerce_review_count_present": ("Review count is present", "Expose review count when reviews exist."),
}
