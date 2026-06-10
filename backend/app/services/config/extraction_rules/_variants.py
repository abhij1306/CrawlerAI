from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from ._common import *
from ._detail import *
from ._detail_sections import *

VARIANT_SIZE_ALIAS_SUFFIXES = (" us",)
# When a second variant axis from one source carries (almost) the same value
# set as an existing axis from another source, the two "axes" are really one
# axis mislabeled (e.g. shoe sizes captured once as `size` and once as `color`).
# Merging them as independent axes would fabricate a Cartesian explosion, so the
# axis is treated as a duplicate when the Jaccard similarity (shared / union of
# values) meets this ratio. Union-based so genuinely distinct numeric axes that
# merely share a value (waist vs inseam) are not collapsed.
VARIANT_MISLABELED_AXIS_MIN_OVERLAP_RATIO = 0.5
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES = (
    "create an account",
    "sign up",
    "updates and promotions",
    # Add-to-cart / add-to-bag call-to-action captured as a variant option
    # (LEGO, REI, Sweetwater — DQ-2 / 2026-05-04 gemini audit).
    "add to cart",
    "add to bag",
    "add to basket",
    "add a lifetime membership to cart",
    # Wishlist / account plumbing strings leaking in as variant labels.
    "account.wishlist",
    "notinlist",
    # Cart/quantity controls picked up as size values.
    "increment quantity",
    "decrement quantity",
    # Payment buttons/badges misclassified as dropdown/radio choices.
    "apple pay",
    "google pay",
    "paypal",
    "shop pay",
    # Fulfillment / shipping banners leaking into variants.
    "pickup unavailable",
    "pickup not available",
    "shipping & returns",
    "for free shipping",
    "choose your location",
    # Marketing / guarantee badges mis-classified as variant axes
    # (ROAM Luggage — DQ-2).
    "change size",
    "features",
    "lifetime warranty",
    "free trial",
    "day free trial",
    "size and weight",
    "see all",
    "view market data",
    "sell now for",
    # Cookie/review/carousel controls captured as variant axes (CE4).
    "your cookie settings",
    "cookie settings",
    "accept all cookies",
    "necessary cookies",
    "targeting cookies",
    "search",
    "close review",
    "compare",
    "previous",
    "next",
    "show image",
    "scroll carousel",
    "keyboard shortcuts",
    "show reviews with",
    "deliver once",
    "now & every",
    "about auto-replenish",
    "auto-replenish save",
    "delivery every week",
    "delivery every 2 weeks",
    "delivery every month",
    "about same-day delivery",
    "same-day delivery free",
    "shipping restrictions",
    "chat support",
    "save to wishlist",
    "saved to wishlist",
    "account wishlist",
    "make offer",
    "buy now",
    "sign in",
    "link your member number",
    "lifetime of benefits",
    "attribute details",
    "more",
    "necessary",
    "functional",
    "performance",
    "targeting",
    "-",
    "+",
)
AMAZON_VARIANT_OPTION_VALUE_NOISE_PHRASES = (
    "shop the store on amazon",
    "play sponsored video",
    "pause sponsored video",
    "mute sponsored video",
)
VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS = frozenset(
    {"select", "choose", "option", "size guide", "your location"}
)
VARIANT_OPTION_VALUE_NOISE_PATTERNS = {
    "fullmatch": (
        r"\d+(?:\.\d+)?\s+stars?",
        r"[-\s]*(?:click\s+to\s+)?(?:choose|select)\b.*",
        r"[-\s]+.+[-\s]+",
        r"\(\d+\)",
        r"\d{3,5}/\d{2,5}/\d{2,5}",
        r"delivery every\s+\d+\s+\w+(?:\s+\(most common\))?",
    ),
    "search": (r"\b(?:please\s+)?select\b",),
}
VARIANT_PLACEHOLDER_VALUES = frozenset(
    {
        "default title",
        "choose",
        "option",
        "select",
        "swatch",
        "size chart",
        "(size chart)",
    }
)
VARIANT_PLACEHOLDER_PREFIXES = ("please select", "open ", "select ")
VARIANT_SIZE_QUANTITY_CONTROL_VALUES = frozenset({"-", "+", "qty", "qty."})
SIZE_REJECT_TOKENS = frozenset(
    {
        "customer reviews",
        "description",
        "details",
        "overview",
        "photos",
        "questions & answers",
        "q&a",
        "ratings",
        "reviews",
        "all",
        "runs small",
        "kinda small",
        "true to size",
        "kinda large",
        "runs large",
        "shipping",
        "specifications",
        "verified purchases",
        "sort by",
        "filter by",
        "price",
        "quantity",
        "qty",
        "qty.",
    }
)
COMMON_WORD_SIZE_VALUES = frozenset(
    {
        "one size",
        "os",
        "queen",
        "king",
        "twin",
        "twin xl",
        "full",
        "full queen",
        "cal king",
        "california king",
        "super single",
        "regular",
        "tall",
        "petite",
        "short",
        "long",
    }
)
ADULT_SIZE_CONTEXT_TOKENS = frozenset(
    {"men", "mens", "women", "womens", "unisex", "adult"}
)
VARIANT_CHILD_SIZE_PATTERNS = (
    r"^nb-\d+lb$",
    r"^\d{1,2}-\d{1,2}m$",
    r"^\d{1,2}t$",
)
VARIANT_SKU_SIZE_SUFFIX_PATTERNS = (
    r"(?:^|[-_/])(?P<size>(?:\d+xl|xxxs|xxs|xs|s|m|l|xl|xxl|xxxl|xxxxl))(?:[-_/](?:19|20)\d{2})?$",
)
VARIANT_CONDITION_HEADER_PREFIXES = ("condition", "quality")
VARIANT_SEPARATE_DIMENSION_SIZE_RULES = (
    {"pattern": r"^\d{2}(?:[srl])$", "style": "Jacket"},
    {"pattern": r"^\d{2}/\d{2}$", "style": "Pant"},
)
PLACEHOLDER_IMAGE_URL_PATTERNS = (
    "via.placeholder.com",
    "placehold.co",
    "placeholder.com",
    "/1x1",
    "1x1.gif",
    "pixel.gif",
    "spacer.gif",
    "blank.gif",
    "transparent.gif",
    "clear.gif",
    # Shopify storefront "no image" placeholder asset (e.g. Glossier).
    "shopifycloud/storefront/assets/no-image",
)
IMAGE_PATH_TOKENS = (
    "/image/",
    "/images/",
    "/media/",
    "/picture",
    "/is/image/",
    "/cdn/",
)
IMAGE_FAMILY_NOISE_TOKENS = frozenset(
    {
        "assets",
        "cdn",
        "crop",
        "detail",
        "default",
        "demandware",
        "editorial",
        "file",
        "files",
        "height",
        "hero",
        "hover",
        "image",
        "images",
        "main",
        "media",
        "picture",
        "product",
        "products",
        "public",
        "static",
        "shop",
        "square",
        "standard",
        "width",
    }
)
WAF_QUEUE_PATTERNS = (
    r"\baccess to this page has been denied\b",
    r"\bsorry for the wait\b",
    r"\bplease wait while we verify\b",
    r"\bwe need to verify\b",
    r"\bjust a moment while we\b",
    r"\bqueue-it\b",
    r"^please wait\b",
    r"\byou are in a virtual queue\b",
)
URL_CONCATENATION_SCHEME_PATTERN = r"https?:/+"
URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS = (
    " ",
    "\t",
    "\n",
    ",",
    ";",
    ")",
    "]",
    "}",
    ">",
)
OPTION_VALUE_NOISE_WORDS = ("popular", "sale", "discount", "off")
VARIANT_PROMO_NOISE_TOKENS = ("off", "discount", "promo")
VARIANT_OPTION_NOISE_PHRASES = ("size guide",)
VARIANT_URL_SUFFIX_CODE_PREFIX_MAX_LEN = 3
VARIANT_COLOR_CODELIKE_TOKEN_PATTERN = r"^(?=.*\d)[A-Za-z0-9]+$"  # nosec B105
TRACKING_STRIP_SURFACE_PREFIXES = ("ecommerce_", "job_")
MAX_TRACKING_KEY_LENGTH = 3
MAX_TRACKING_VALUE_LENGTH = 8
SCOPE_PRODUCT_CONTEXT_TOKENS = ("product", "detail", "pdp")
SCOPE_SCORE_MAIN_WEIGHT = 4000
SCOPE_SCORE_PRIORITY_WEIGHT = 2000
SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT = 1000
MAX_SELECTOR_MATCHES = 12
VARIANT_CHOICE_OPTION_SELECTOR = (
    "option, [role='radio'], [role='option'], button, a[href], "
    "a[class*='swatch' i][title], a[class*='swatch' i][aria-label], "
    "input[type='radio'], input[type='checkbox']"
)
VARIANT_CHOICE_OPTION_LIMIT = 80
VARIANT_CHOICE_CONTAINER_OPTION_LIMIT = 24
VARIANT_CHOICE_CONTAINER_SELECT_LIMIT = 8
VARIANT_CHOICE_CONTAINER_GROUP_LIMIT = 12
VARIANT_CHOICE_CONTAINER_MIN_DISTINCT_NAMES = 2

# Selector for individual variant option controls used when reconciling
# already-extracted variant rows against rendered-DOM availability cues. This
# covers radio/checkbox inputs, role=radio/option nodes, select <option>s, and
# swatch/size buttons that carry a value/label and a disabled/OOS signal.
VARIANT_OPTION_CONTROL_SELECTOR = (
    "option, input[type='radio'], input[type='checkbox'], "
    "[role='radio'], [role='option'], "
    "button[value], button[data-option-id], button[data-value], "
    "button[aria-label], a[class*='swatch' i][title], "
    "a[class*='swatch' i][aria-label], [data-testid='swatch' i], "
    "[data-testid*='swatch-option' i]"
)
VARIANT_OPTION_CONTROL_SCAN_LIMIT = 300
# Attributes on an option control whose value carries a join key back to an
# extracted variant row (the option/SKU/variant value or label).
VARIANT_OPTION_CONTROL_KEY_ATTRIBUTES = (
    "value",
    "data-value",
    "data-option-value",
    "data-size",
    "data-sku",
    "data-variant-id",
    "data-option-id",
    "aria-label",
    "title",
)

__all__ = sorted(name for name in globals() if name.isupper())
