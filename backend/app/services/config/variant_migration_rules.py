from __future__ import annotations

from app.services.config.extraction_rules import DETAIL_VARIANT_CONTEXT_NOISE_TOKENS

DETAIL_VARIANT_CONTEXT_NOISE_TOKENS_EXTRA = (
    "tabs",
    "tab-list",
    "tablist",
    "tab-nav",
    "reviews",
    "review-section",
    "ratings",
    "social",
    "share-bar",
    "protection",
    "warranty",
)
VARIANT_CONTEXT_NOISE_TOKENS = frozenset(
    str(token).strip().lower()
    for token in (
        *tuple(DETAIL_VARIANT_CONTEXT_NOISE_TOKENS or ()),
        *tuple(DETAIL_VARIANT_CONTEXT_NOISE_TOKENS_EXTRA or ()),
    )
    if str(token).strip()
)
DETAIL_VARIANT_SOFT_SCOPE_SELECTOR = (
    "[class*='variant' i], [class*='option' i], [class*='selector' i], "
    "[class*='swatch' i], [id*='variant' i], [id*='option' i], "
    "[id*='selector' i], [id*='swatch' i], [data-testid*='variant' i], "
    "[data-testid*='swatch' i], [data-component*='variant' i], fieldset, "
    "[role='radiogroup'], [role='group'][aria-label], select"
)
VARIANT_SCOPE_SOURCE_TRUSTED = "trusted_scope"
VARIANT_SCOPE_SOURCE_SOFT = "soft_scope"
VARIANT_SCOPE_SOURCE_FULL_PAGE = "full_page"
VARIANT_COLOR_AXIS_FIELD = "color"
VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS = 2
VARIANT_SOFT_SCOPE_MIN_RADIO_INPUTS_FALLBACK = 2
VARIANT_SOFT_SCOPE_FIELDSET_SIGNAL_SELECTOR = (
    "input[type='radio'], input[type='checkbox'], "
    "[role='radio'], [role='option'], button, [data-option-value]"
)
VARIANT_SOFT_SCOPE_ROLE_OPTION_SELECTOR = (
    "a[href], button, [data-testid='swatch' i], [data-testid*='swatch-option' i]"
)
VARIANT_SOFT_SCOPE_STRONG_NODE_SELECTOR = (
    "input[type='radio'], input[type='checkbox'], "
    "[role='radio'], [role='button'], [data-option], [data-option-value], "
    "[data-selected], [data-testid='swatch' i], [data-testid*='swatch-option' i], "
    "button, a[href]"
)
VARIANT_OPTION_ATTRIBUTE_NAMES = (
    "data-option",
    "data-option-value",
    "data-variant",
)
VARIANT_SELECTED_SIGNAL_ATTRIBUTE_NAMES = (
    "data-selected",
    "aria-current",
    "aria-pressed",
)
VARIANT_SELECTED_SIGNAL_TRUE_VALUES = frozenset(
    {"1", "checked", "current", "selected", "true", "yes"}
)
VARIANT_SELECTED_SIGNAL_TOKENS = ("selected", "current", "checked")
VARIANT_CONFIDENT_OPTION_NODE_TYPES = frozenset(
    {
        "input_radio",
        "input_checkbox",
        "role_radio",
        "role_option",
        "option",
        "data_selected",
    }
)
VARIANT_CONTAINER_CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})
VARIANT_CONTAINER_SEMANTIC_TOKENS = (
    "variant",
    "option",
    "selector",
    "swatch",
    "swatches",
    "swatchesdisplay",
    "radiogroup",
)
VARIANT_PUBLIC_URL_FIELD_NAMES = ("url", "image_url")
VARIANT_PUBLIC_URL_SCHEMES = frozenset({"http", "https"})
VARIANT_PRODUCT_DETAIL_PATH_MARKERS = (
    "/products/",
    "/product/",
    "/p/",
    "/dp/",
    "/c/product/",
    "/catalog/product/",
)
VARIANT_URL_BLOCKED_PATH_SUFFIXES = frozenset(
    {
        "/reviews",
        "/review",
        "/print",
        "/share",
        "/overview",
        "/specifications",
        "/specs",
        "/wishlist",
        "/cart",
        "/returns-policy",
        "/credit",
        "/payment",
        "/help",
    }
)
VARIANT_URL_BLOCKED_PATH_PREFIXES = frozenset(
    {
        "/pl/",
        "/c/",
        "/collections/",
        "/category/",
        "/browse/",
        "/search/",
        "/l/",
    }
)
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES_EXTRA = (
    "view more",
    "view all",
    "view all images",
    "view all photos",
    "overview",
    "specifications",
    "description",
    "features",
    "share",
    "print",
    "save",
    "bookmark",
    "show more",
    "more details",
    "see details",
    "return policy",
    "returns policy",
    "payment options",
    "shop the collection",
    "shop all",
    "year protection plan",
    "protection plan",
    "extended warranty",
    "increment or decrement number",
    "increment or decrement",
)
VARIANT_OPTION_VALUE_NOISE_FULLMATCH_PATTERNS_EXTRA = (
    r"\d+\+?\s+reviews?",
    r"\d+\+?\s+ratings?",
    r"(\b\w+\b)(?:\s+\1)+",
    r"shop\s+\w+(?:\s+\w+){0,2}",
)
VARIANT_STRONG_OPTION_SELECTOR = (
    "[role='radio'], [role='option'], input[type='radio'], input[type='checkbox'], "
    "[data-option-value], [data-value], [data-variant-id], [data-selected], "
    "[aria-pressed][aria-pressed!=''], button[data-option], button[data-value], "
    "button[data-variant], a[class*='swatch' i][title], "
    "a[class*='swatch' i][aria-label], [data-testid='swatch' i], "
    "[data-testid*='swatch-option' i]"
)
VARIANT_WEAK_OPTION_SELECTOR = (
    "button:not([data-dismiss]):not([type='submit']):not([type='reset']), "
    "a[href], a[class*='swatch' i][title], a[class*='swatch' i][aria-label]"
)
VARIANT_GROUP_MIN_CONFIDENCE = 0.35
