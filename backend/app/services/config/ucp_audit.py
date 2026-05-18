from __future__ import annotations

UCP_MANIFEST_PATH = "/.well-known/ucp"
UCP_DEFAULT_URL_SCHEME = "https"
UCP_REQUIRED_CAPABILITIES = (
    "product_discovery",
    "checkout",
    "orders",
)
UCP_REQUIRED_SERVICE_NAMES = ("dev.ucp.shopping",)

UCP_SAMPLE_DISCOVERY_PATHS = (
    "/sitemap.xml",
    "/",
)
UCP_SAMPLE_CHILD_SITEMAP_LIMIT = 3
UCP_SAMPLE_FETCH_CONCURRENCY = 3
UCP_PRODUCT_URL_MARKERS = (
    "/products/",
    "/product/",
    "/p/",
    "/dp/",
)

UCP_HTTP_ONLY_MODE = "http_only"
UCP_BROWSER_ONLY_MODE = "browser_only"
UCP_AUDIT_SURFACE = "ecommerce_detail"
UCP_DISCOVERY_TIMEOUT_SECONDS = 5.0
UCP_AGENT_UA_OVERRIDE: str | None = None

UCP_AUDIT_JOB_STATUS_QUEUED = "queued"
UCP_AUDIT_JOB_STATUS_RUNNING = "running"
UCP_AUDIT_JOB_STATUS_COMPLETE = "complete"
UCP_AUDIT_JOB_STATUS_FAILED = "failed"
UCP_AUDIT_DEFAULT_SAMPLE_SIZE = 5
UCP_AUDIT_MAX_SAMPLE_SIZE = 50
UCP_AUDIT_DEFAULT_INCLUDE_AGENT_DELTA = False
UCP_AUDIT_DEFAULT_REPORT_FORMATS = ("json", "markdown")

JSON_LD_TYPE_KEY = "@type"
JSON_LD_PRODUCT_TYPES = frozenset({"Product", "ProductGroup"})
JSON_LD_NAME_FIELD = "name"
JSON_LD_VALUE_FIELD = "value"
JSON_LD_OFFERS_FIELD = "offers"
JSON_LD_ADDITIONAL_PROPERTY_FIELD = "additionalProperty"
JSON_LD_CATEGORY_FIELDS = ("product_type", "category")
JSON_LD_REQUIRED_FIELD_PATHS = (
    ("name",),
    ("offers", "price"),
    ("offers", "availability"),
    ("offers", "priceCurrency"),
)
JSON_LD_RECOMMENDED_FIELD_PATHS = (
    ("sku",),
    ("brand",),
    ("gtin13",),
    ("description",),
    ("image",),
)

UCP_CRITICAL_ATTRIBUTES = (
    "color",
    "size",
    "material",
    "brand",
    "gtin",
)
UCP_METAFIELD_COVERAGE_THRESHOLD = 0.7
UCP_CATEGORY_DEPTH_MIN = 3
UCP_CATEGORY_DEPTH_SEPARATORS = (">", "/")

PUBLIC_VARIANTS_FIELD = "variants"
PUBLIC_VARIANT_SKU_FIELD = "sku"
PUBLIC_VARIANT_PRICE_FIELD = "price"
PUBLIC_VARIANT_CURRENCY_FIELD = "currency"
PUBLIC_VARIANT_AVAILABILITY_FIELD = "availability"
POLICY_JSONLD_SHIPPING_FIELD = "shippingDetails"
POLICY_JSONLD_CURRENCY_FIELD = "priceCurrency"
POLICY_SCORE_PER_SIGNAL = 25
ISO4217_PATTERN = r"^[A-Z]{3}$"

FINDING_VARIANT_OFFERS_COLLAPSED = "variant_offers_collapsed"
FINDING_PRICE_INTEGRITY_DISCOUNT_MISMATCH = "price_integrity_discount_mismatch"
FINDING_VARIANT_SKU_MISSING = "variant_sku_missing"
FINDING_VARIANT_AVAILABILITY_MISSING = "variant_availability_missing"
FINDING_POLICY_SHIPPING_MISSING = "policy_shipping_missing"
FINDING_POLICY_RETURN_PERIOD_MISSING = "policy_return_period_missing"
FINDING_POLICY_CURRENCY_INVALID = "policy_currency_invalid"
FINDING_POLICY_PAGE_INACCESSIBLE = "policy_page_inaccessible"
FINDING_AGENT_DELTA_LOW_FIDELITY = "agent_delta_low_fidelity"
FINDING_AGENT_DELTA_DISABLED = "agent_delta_disabled"
FINDING_AGENT_DELTA_UNAVAILABLE = "agent_delta_unavailable"
FINDING_MANIFEST_MISSING = "manifest_missing"
FINDING_MANIFEST_INVALID = "manifest_invalid"
FINDING_DIMENSION_NOT_EVALUATED = "dimension_not_evaluated"
FINDING_PRODUCT_SAMPLE_MISSING = "product_sample_missing"
FINDING_PRODUCT_JSONLD_MISSING = "product_jsonld_missing"
FINDING_PRODUCT_SCHEMA_REQUIRED_MISSING = "product_schema_required_missing"
FINDING_PRODUCT_SCHEMA_RECOMMENDED_MISSING = "product_schema_recommended_missing"
FINDING_PRODUCT_ADDITIONAL_PROPERTY_MISSING = "product_additional_property_missing"
FINDING_METAFIELD_CRITICAL_GAP = "metafield_critical_gap"
FINDING_TAXONOMY_INCONSISTENT = "taxonomy_inconsistent"

D_UCP1_ID = "D-UCP1"
D_UCP2_ID = "D-UCP2"
D_UCP3_ID = "D-UCP3"
D_UCP4_ID = "D-UCP4"
D_UCP5_ID = "D-UCP5"
D_UCP6_ID = "D-UCP6"
D_UCP7_ID = "D-UCP7"
UCP_STATUS_PASS = "pass"
UCP_STATUS_WARNING = "warning"
UCP_STATUS_FAIL = "fail"
UCP_FINDING_BLOCKING = "blocking"
UCP_FINDING_WARNING = "warning"
UCP_FINDING_INFO = "info"
DIMENSION_WEIGHTS = {
    D_UCP1_ID: 0.2,
    D_UCP2_ID: 0.15,
    D_UCP3_ID: 0.15,
    D_UCP4_ID: 0.1,
    D_UCP5_ID: 0.15,
    D_UCP6_ID: 0.1,
    D_UCP7_ID: 0.15,
}
D_UCP1_GATE_MAX_SCORE = 30
AGENT_DELTA_BLOCKING_THRESHOLD = 0.3
AGENT_DELTA_HUMAN_REQUESTED_FIELDS = (
    "title",
    "price",
    "currency",
    "availability",
    "variants",
    "color",
    "size",
)
AGENT_DELTA_HUMAN_MAX_RECORDS = 1
AGENT_DELTA_COLOR_LABEL = "Color"
AGENT_DELTA_SIZE_LABEL = "Select Size"
AGENT_DELTA_COLOR_STOP_LABELS = (
    "Select Size",
    "Size Guide",
    "Quantity",
    "Free Shipping",
    "Don't Forget to Add",
    "Add to Cart",
    "Features",
)
AGENT_DELTA_SIZE_STOP_LABELS = (
    "Size Guide",
    "Quantity",
    "ADD TO CART",
    "Add to cart",
    "Or, Try On In Store.",
)
AGENT_DELTA_OPTION_MAX_COUNT = 12
AGENT_DELTA_OPTION_MAX_CHARS = 24
AGENT_DELTA_COLOR_OPTION_MAX_WORDS = 3
AGENT_DELTA_SIZE_OPTION_MAX_WORDS = 5
AGENT_DELTA_OPTION_INVALID_CHARS = frozenset({'"', "'", "(", ")", "[", "]", "{", "}"})
AGENT_DELTA_OPTION_NOISE_LINES = frozenset(
    {
        "quantity",
        "decrease quantity",
        "increase quantity",
        "add to cart",
        "add to bag",
        "sold out",
        "or, try on in store.",
        "price",
        "add",
        "shop now",
        "powered by rebuy",
        "features",
        "how to apply magic press",
    }
)
