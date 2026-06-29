"""Knowledge Graph configuration: types, statuses, bounds, and tunables.

This module is the single owner of the Knowledge Graph vocabulary and the
runtime knobs that govern projection and the read API. It is *data only* — no
database access, no models, no logic — so it can be imported by config-level
ratchets and by the later projection/API slices without creating a dependency
cycle. Tables, repository, and projector arrive in Slices 5-8; they consume
these constants rather than redefining them.

Vocabulary and bounds trace directly to the feature spec
(`docs/feature specs/site-product-knowledge-graph.md`, §4-§6) and the master
plan's API read-bound decisions.
"""

from __future__ import annotations

from typing import Final

# --- Node and edge vocabulary (feature spec §4.3) ---------------------------

KG_NODE_TYPES: Final = frozenset(
    {
        "site",
        "technology",
        "page_template",
        "route_pattern",
        "canonical_field",
        "source_pattern",
        "page",
        "product",
        "offer",
        "brand",
        "category",
        "seller",
        "asset",
    }
)

KG_EDGE_TYPES: Final = frozenset(
    {
        "SITE_USES_TECHNOLOGY",
        "SITE_HAS_TEMPLATE",
        "TEMPLATE_MATCHES_ROUTE",
        "TEMPLATE_EXPOSES_FIELD",
        "SOURCE_PROVIDES_FIELD",
        "PAGE_INSTANCE_OF_TEMPLATE",
        "PAGE_MENTIONS_PRODUCT",
        "PRODUCT_HAS_OFFER",
        "PRODUCT_MADE_BY",
        "PRODUCT_IN_CATEGORY",
        "OFFER_SOLD_BY",
        "PRODUCT_HAS_ASSET",
        "PRODUCT_SAME_AS",
    }
)

KG_PRODUCT_IDENTITY_FACTS: Final = (
    "product.gtin",
    "product.mpn",
    "product.sku",
    "product.url",
)
KG_PRODUCT_GTIN_FACT: Final = "product.gtin"
KG_PRODUCT_MPN_FACT: Final = "product.mpn"
KG_PRODUCT_SKU_FACT: Final = "product.sku"
KG_PRODUCT_URL_FACT: Final = "product.url"
KG_PRODUCT_BRAND_FACT: Final = "product.brand"
KG_PRODUCT_CATEGORY_FACT: Final = "product.category"
KG_OFFER_SELLER_FACT: Final = "offer.seller"
KG_ASSET_URL_FACT: Final = "asset.image_url"
KG_VARIANT_SET_FACT: Final = "product.variant_set"

KG_PRODUCT_BRAND_RELATIONSHIP: Final = "PRODUCT_MADE_BY"
KG_PRODUCT_CATEGORY_RELATIONSHIP: Final = "PRODUCT_IN_CATEGORY"
KG_PRODUCT_OFFER_RELATIONSHIP: Final = "PRODUCT_HAS_OFFER"
KG_OFFER_SELLER_RELATIONSHIP: Final = "OFFER_SOLD_BY"
KG_PRODUCT_ASSET_RELATIONSHIP: Final = "PRODUCT_HAS_ASSET"
KG_PRODUCT_SAME_AS_RELATIONSHIP: Final = "PRODUCT_SAME_AS"

# --- Statuses ----------------------------------------------------------------

# Entity / relationship / claim lifecycle. A new observation supersedes the
# prior winner without erasing it; explicit retraction is operator-driven.
KG_ENTITY_STATUSES: Final = frozenset({"active", "superseded", "retracted"})

# Per-site projection state recorded on `kg_site_versions` (feature spec §4.2).
KG_PROJECTION_STATUSES: Final = frozenset(
    {"pending", "projecting", "projected", "failed"}
)

# --- Extraction contracts (feature spec §5) ---------------------------------

# How a contract's chosen source was decided. `llm_proposed` is always inert
# until an operator promotes it; the runtime never auto-activates it.
KG_SELECTION_ORIGINS: Final = frozenset({"generic", "operator", "llm_proposed"})

# Recorded per field in `diagnose.json` when a frozen contract is in play.
KG_CONTRACT_OUTCOMES: Final = frozenset(
    {"hit", "miss", "fallback", "stale_source", "override_miss"}
)

# --- Deterministic product identity ladder (feature spec §4.4) --------------

# Strict order; the first available identifier wins. Title / vector / LLM
# similarity may only seed non-authoritative candidate edges, never a
# `PRODUCT_SAME_AS` edge on their own.
KG_IDENTITY_LADDER: Final = (
    "gtin",
    "manufacturer_mpn",
    "site_product_id",
    "site_sku",
    "canonical_url",
)

# --- Read-API bounds (master plan, API section) -----------------------------

KG_DEFAULT_GRAPH_DEPTH: Final = 2
KG_MAX_GRAPH_DEPTH: Final = 4
KG_DEFAULT_NODE_LIMIT: Final = 200
KG_MAX_NODE_LIMIT: Final = 500

# --- Projection tunables -----------------------------------------------------

# Bounded provenance keeps the graph small (feature spec §4.5, §6.2).
KG_CONTRACT_RETAINED_VALUE_LIMIT: Final = 5
KG_CLAIM_VALUE_PREVIEW_LIMIT: Final = 120

# --- Runtime snapshot bounds (Slice 7) ---------------------------------------

# Freeze a bounded set of templates and contracts at run creation.
KG_SNAPSHOT_TEMPLATE_LIMIT: Final = 50
KG_SNAPSHOT_CONTRACT_LIMIT: Final = 50

__all__ = [
    "KG_CLAIM_VALUE_PREVIEW_LIMIT",
    "KG_CONTRACT_OUTCOMES",
    "KG_CONTRACT_RETAINED_VALUE_LIMIT",
    "KG_DEFAULT_GRAPH_DEPTH",
    "KG_DEFAULT_NODE_LIMIT",
    "KG_EDGE_TYPES",
    "KG_ENTITY_STATUSES",
    "KG_IDENTITY_LADDER",
    "KG_ASSET_URL_FACT",
    "KG_OFFER_SELLER_FACT",
    "KG_OFFER_SELLER_RELATIONSHIP",
    "KG_PRODUCT_ASSET_RELATIONSHIP",
    "KG_PRODUCT_BRAND_FACT",
    "KG_PRODUCT_BRAND_RELATIONSHIP",
    "KG_PRODUCT_CATEGORY_FACT",
    "KG_PRODUCT_CATEGORY_RELATIONSHIP",
    "KG_PRODUCT_GTIN_FACT",
    "KG_PRODUCT_IDENTITY_FACTS",
    "KG_PRODUCT_MPN_FACT",
    "KG_PRODUCT_OFFER_RELATIONSHIP",
    "KG_PRODUCT_SAME_AS_RELATIONSHIP",
    "KG_PRODUCT_SKU_FACT",
    "KG_PRODUCT_URL_FACT",
    "KG_VARIANT_SET_FACT",
    "KG_MAX_GRAPH_DEPTH",
    "KG_MAX_NODE_LIMIT",
    "KG_NODE_TYPES",
    "KG_PROJECTION_STATUSES",
    "KG_SELECTION_ORIGINS",
    "KG_SNAPSHOT_CONTRACT_LIMIT",
    "KG_SNAPSHOT_TEMPLATE_LIMIT",
]
