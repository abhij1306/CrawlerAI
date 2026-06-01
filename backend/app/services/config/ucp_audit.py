from __future__ import annotations

UCP_MANIFEST_PATH = "/.well-known/ucp"
UCP_DEFAULT_URL_SCHEME = "https"
UCP_TARGET_VERSION = "2026-04-08"
UCP_ACCEPT_HEADER = "application/json, application/vnd.ucp+json;q=0.9"
UCP_DISCOVERY_TIMEOUT_SECONDS = 5.0
UCP_SCHEMA_TIMEOUT_SECONDS = 5.0
UCP_TRANSPORT_TIMEOUT_SECONDS = 5.0
UCP_SCHEMA_LLM_TIMEOUT_SECONDS = 20.0
UCP_AUDIT_PLATFORM_PROFILE_URL = "https://your-audit-platform.example.com/.well-known/ucp"

UCP_AUDIT_JOB_STATUS_QUEUED = "queued"
UCP_AUDIT_JOB_STATUS_RUNNING = "running"
UCP_AUDIT_JOB_STATUS_COMPLETE = "complete"
UCP_AUDIT_JOB_STATUS_FAILED = "failed"
UCP_AUDIT_DEFAULT_SAMPLE_SIZE = 5
UCP_AUDIT_MAX_SAMPLE_SIZE = 50
UCP_AUDIT_DEFAULT_REPORT_FORMATS = ("json", "markdown")

UCP_MANIFEST_MODE = "manifest"
UCP_MCP_MODE = "mcp"
UCP_SCHEMA_MODE = "schema"
UCP_SHOP_SKILL_MODE = "shop_skill"

UCP_SHOPPING_SERVICE = "dev.ucp.shopping"
UCP_REQUIRED_SERVICE_NAMES = (UCP_SHOPPING_SERVICE,)
UCP_REQUIRED_CAPABILITIES = (
    "dev.ucp.shopping.catalog.search",
    "dev.ucp.shopping.catalog.lookup",
    "dev.ucp.shopping.cart",
    "dev.ucp.shopping.checkout",
    "dev.ucp.shopping.order",
    "dev.ucp.shopping.fulfillment",
    "dev.ucp.shopping.discount",
)
UCP_REQUIRED_CATALOG_CAPABILITIES = (
    "dev.ucp.shopping.catalog.search",
    "dev.ucp.shopping.catalog.lookup",
)
UCP_REQUIRED_CART_CHECKOUT_CAPABILITIES = (
    "dev.ucp.shopping.cart",
    "dev.ucp.shopping.checkout",
)
UCP_REQUIRED_ORDER_POLICY_CAPABILITIES = (
    "dev.ucp.shopping.order",
    "dev.ucp.shopping.fulfillment",
    "dev.ucp.shopping.discount",
)
UCP_REQUIRED_SCHEMA_KEYWORDS = {
    "catalog": ("catalog", "product", "search", "lookup", "shopping"),
    "cart_checkout": ("cart", "checkout", "shopping"),
    "order_policy": ("order", "fulfillment", "discount", "policy", "return", "shopping"),
}
UCP_REQUIRED_SCHEMA_FIELDS = {
    "catalog": ("product_id", "title", "price", "currency", "availability"),
    "cart_checkout": ("cart_id", "line_items", "total", "currency"),
    "order_policy": ("order_id", "status", "fulfillment"),
}
UCP_SAFE_READ_ONLY_TOOL_KEYWORDS = ("catalog", "search", "lookup", "product")
UCP_SIDE_EFFECT_TOOL_KEYWORDS = (
    "cart",
    "checkout",
    "order",
    "payment",
    "fulfillment",
    "discount",
)

UCP_STATUS_PASS = "pass"  # nosec B105
UCP_STATUS_WARNING = "warning"
UCP_STATUS_FAIL = "fail"
UCP_FINDING_BLOCKING = "blocking"
UCP_FINDING_WARNING = "warning"
UCP_FINDING_INFO = "info"

D_UCP1_ID = "D-UCP1"
D_UCP2_ID = "D-UCP2"
D_UCP3_ID = "D-UCP3"
D_UCP4_ID = "D-UCP4"
D_UCP5_ID = "D-UCP5"
D_UCP6_ID = "D-UCP6"
DIMENSION_WEIGHTS = {
    D_UCP1_ID: 0.2,
    D_UCP2_ID: 0.2,
    D_UCP3_ID: 0.15,
    D_UCP4_ID: 0.15,
    D_UCP5_ID: 0.15,
    D_UCP6_ID: 0.15,
}
D_UCP1_GATE_MAX_SCORE = 30
D_UCP3_GATE_MAX_SCORE = 45

FINDING_MANIFEST_MISSING = "manifest_missing"
FINDING_MANIFEST_INVALID = "manifest_invalid"
FINDING_MANIFEST_CONTENT_TYPE_INVALID = "manifest_content_type_invalid"
FINDING_MANIFEST_REDIRECTED = "manifest_redirected"
FINDING_SIGNING_KEYS_MISSING = "signing_keys_missing"
FINDING_CACHE_CONTROL_MISSING = "cache_control_missing"
FINDING_SERVICE_MISSING = "service_missing"
FINDING_SERVICE_INVALID = "service_invalid"
FINDING_CAPABILITY_MISSING = "capability_missing"
FINDING_CAPABILITY_INVALID = "capability_invalid"
FINDING_CAPABILITY_VERSION_MISMATCH = "capability_version_mismatch"
FINDING_TRANSPORT_MISSING = "transport_missing"
FINDING_TRANSPORT_UNREACHABLE = "transport_unreachable"
FINDING_TRANSPORT_NEGOTIATION_INCOMPLETE = "transport_negotiation_incomplete"
FINDING_SCHEMA_MISSING = "schema_missing"
FINDING_SCHEMA_UNREACHABLE = "schema_unreachable"
FINDING_SCHEMA_FIELD_MISSING = "schema_field_missing"
FINDING_CATALOG_CONTRACT_MISSING = "catalog_contract_missing"
FINDING_CART_CHECKOUT_CONTRACT_MISSING = "cart_checkout_contract_missing"
FINDING_ORDER_POLICY_CONTRACT_MISSING = "order_policy_contract_missing"
FINDING_PAYMENT_HANDLER_MISSING = "payment_handler_missing"

UCP_SCHEMA_ANALYSIS_LLM_TASK = "ucp_schema_analysis"
UCP_AUDIT_PROMPT_REGISTRY = {
    UCP_SCHEMA_ANALYSIS_LLM_TASK: {
        "response_type": "object",
        "system_file": "ucp_schema_analysis.system.txt",
        "user_file": "ucp_schema_analysis.user.txt",
    },
}
