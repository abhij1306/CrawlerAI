"""Code-owned field names and aliases for the four explicit surfaces."""

from __future__ import annotations

import re
from typing import Any

from app.core.config.extraction_price_rules import (
    DETAIL_EXPLICIT_MINOR_UNIT_PRICE_FIELDS,
)

TITLE_FIELD = "title"
URL_FIELD = "url"
APPLY_URL_FIELD = "apply_url"
CANONICAL_URL_FIELD = "canonical_url"
PRICE_FIELD = "price"
CURRENCY_FIELD = "currency"
IMAGE_URL_FIELD = "image_url"
ADDITIONAL_IMAGES_FIELD = "additional_images"
COLOR_FIELD = "color"
SIZE_FIELD = "size"
WEIGHT_FIELD = "weight"
WIDTH_FIELD = "width"
AVAILABILITY_FIELD = "availability"
STOCK_QUANTITY_FIELD = "stock_quantity"
VARIANTS_FIELD = "variants"
AVAILABLE_SIZES_FIELD = "available_sizes"
VARIANT_AXES_FIELD = "variant_axes"
SELECTED_VARIANT_FIELD = "selected_variant"
BARCODE_FIELD = "barcode"
SKU_FIELD = "sku"
PRODUCT_ID_FIELD = "product_id"
ROUTE_BARCODE_TO_SKU = True

ASSET_IMAGE_URL_FACT_TYPE = "asset.image_url"
OFFER_AVAILABILITY_FACT_TYPE = "offer.availability"
OFFER_CURRENCY_FACT_TYPE = "offer.currency"
OFFER_ORIGINAL_PRICE_FACT_TYPE = "offer.original_price"
OFFER_PRICE_FACT_TYPE = "offer.price"
ECOMMERCE_DISPLAY_PRICE_SOURCE_KEYS = (
    "formattedPrice",
    "formatted_price",
    "displayPrice",
    "display_price",
    "priceText",
    "price_text",
)
PRODUCT_BRAND_FACT_TYPE = "product.brand"
PRODUCT_DESCRIPTION_FACT_TYPE = "product.description"
PRODUCT_GTIN_FACT_TYPE = "product.gtin"
PRODUCT_MPN_FACT_TYPE = "product.mpn"
PRODUCT_SKU_FACT_TYPE = "product.sku"
PRODUCT_TITLE_FACT_TYPE = "product.title"
PRODUCT_URL_FACT_TYPE = "product.url"
VARIANT_GTIN_FACT_TYPE = "variant.gtin"
VARIANT_SKU_FACT_TYPE = "variant.sku"

FIELD_ALIASES: dict[str, list[str]] = {
    "title": ["title", "name", "job_title", "position", "headline", "productName"],
    "url": [
        "url",
        "link",
        "href",
        "canonical_url",
        "product_url",
        "pdp_url",
        "detail_url",
        "workUrl",
        "listingUrl",
        "positionURI",
    ],
    "price": ["price", "amount", "cost", "current_price", "lowPrice"],
    "original_price": [
        "compare_at_price",
        "list_price",
        "regular_price",
        "was_price",
        "original_price",
    ],
    "currency": ["currency", "currency_code", "price_currency"],
    "brand": [
        "brand",
        "brand_name",
        "brandName",
        "brand_label",
        "manufacturer",
        "manufacturer_name",
        "manufacturerName",
        "designer",
        "designer_name",
        "designerName",
    ],
    "image_url": [
        "image",
        "image_url",
        "thumbnail",
        "img",
        "photo",
        "featured_image",
        "primary_image",
    ],
    "additional_images": [
        "images",
        "gallery",
        "product_images",
        "media",
        "photos",
        "assets",
    ],
    "color": ["color", "colors", "color_name", "finish", "colour"],
    "size": ["size", "sizes", "variant_size"],
    "variants": ["variants", "variant_rows", "variant_matrix"],
    "materials": ["materials", "material", "fabric", "composition", "fabric_content"],
    "care": ["care", "care_instructions", "product_care"],
    "company": [
        "company",
        "company_name",
        "organization",
        "employer",
        "hiring_organization",
    ],
    "location": ["location", "job_location", "city", "region"],
    "salary": ["salary", "compensation", "pay", "salary_range"],
    "job_id": ["job_id", "jobId", "requisition_id", "req_id", "opening_id"],
    "category": [
        "category",
        "product_type",
        "breadcrumb",
        "breadcrumbs",
        "category_path",
    ],
    "gender": ["gender", "target_gender", "targetGender"],
    "sku": ["sku", "item_id", "id"],
    "availability": ["availability", "in_stock", "stock_status", "inStock"],
    "rating": ["rating", "average_rating", "score", "rating_value"],
    "review_count": ["review_count", "total_reviews", "num_reviews", "numberOfReviews"],
    "stock_quantity": ["stock_quantity", "inventory_quantity", "quantity_available"],
    "posted_date": ["posted_date", "date_posted", "posted_at"],
    "apply_url": ["apply_url", "application_url", "job_url"],
    "responsibilities": ["responsibilities", "duties", "job_duties"],
    "qualifications": [
        "qualifications",
        "minimum_requirements",
        "preferred_qualifications",
    ],
    "benefits": ["benefits", "job_benefits", "perks", "what_we_offer"],
    "skills": ["skills", "job_skills", "competencies"],
    "remote": ["remote", "work_from_home", "wfh", "telecommute"],
    "job_type": ["job_type", "employment_type", "type"],
    "specifications": ["specifications", "details", "technical_details"],
    "product_details": ["product_details", "product details"],
    "features": ["features", "highlights", "key_features"],
    "dimensions": ["dimensions", "sizing", "measurements"],
    "summary": ["summary", "excerpt", "description"],
    "requirements": ["requirements", "job_requirements", "prerequisites"],
    "description": ["description", "product description", "product_description"],
    "tables": ["tables", "table", "data_tables", "spec_tables"],
}

CANONICAL_SCHEMAS: dict[str, list[str]] = {
    "ecommerce_detail": [
        "title",
        "canonical_url",
        "brand",
        "sku",
        "barcode",
        "product_id",
        "part_number",
        "price",
        "original_price",
        "currency",
        "availability",
        "image_url",
        "additional_images",
        "description",
        "rating",
        "review_count",
        "category",
        "gender",
        "color",
        "size",
        "materials",
        "care",
        "features",
        "specifications",
        "product_details",
        "tags",
        "variants",
        "variant_count",
        "tables",
    ],
    "ecommerce_listing": [
        "title",
        "brand",
        "sku",
        "price",
        "original_price",
        "currency",
        "availability",
        "image_url",
        "color",
        "size",
        "description",
        "rating",
        "review_count",
        "url",
    ],
    "job_detail": [
        "title",
        "company",
        "location",
        "salary",
        "job_type",
        "posted_date",
        "apply_url",
        "description",
        "requirements",
        "responsibilities",
        "qualifications",
        "benefits",
        "skills",
        "remote",
        "tables",
    ],
    "job_listing": [
        "title",
        "job_id",
        "company",
        "location",
        "salary",
        "job_type",
        "posted_date",
        "department",
        "description",
        "url",
        "apply_url",
    ],
}

PROMPT_REGISTRY = {
    "direct_record_extraction": {
        "response_type": "array",
        "system_file": "direct_record_extraction.system.txt",
        "user_file": "direct_record_extraction.user.txt",
    },
    "field_cleanup_review": {
        "response_type": "object",
        "system_file": "field_cleanup_review.system.txt",
        "user_file": "field_cleanup_review.user.txt",
    },
    "missing_field_extraction": {
        "response_type": "object",
        "system_file": "missing_field_extraction.system.txt",
        "user_file": "missing_field_extraction.user.txt",
    },
}

NAVIGATION_URL_FIELDS = frozenset({URL_FIELD, APPLY_URL_FIELD, CANONICAL_URL_FIELD})
BRAND_LIKE_FIELDS = frozenset({"brand", "company", "dealer_name", "vendor"})
INTERNAL_ONLY_FIELDS = frozenset({"_source", "_score", "slug", "_raw_item"})
OPEN_FIELD_SURFACES: frozenset[str] = frozenset()
NORMALIZER_BOOLEAN_FIELDS = frozenset({"remote"})
NORMALIZER_DECIMAL_FIELDS = frozenset(
    {
        "discount_amount",
        "discount_percentage",
        "original_price",
        "price",
        "rating",
        "sale_price",
        "salary_max",
        "salary_min",
    }
)
NORMALIZER_INTEGER_FIELDS = frozenset(
    {
        "image_count",
        "job_id",
        "quantity",
        "rating_count",
        "reading_time",
        "reply_count",
        "review_count",
        "stock_quantity",
        "variant_count",
        "view_count",
        "word_count",
    }
)
NORMALIZER_LIST_TEXT_FIELDS = frozenset({"additional_images", "features", "tags"})
DOM_HIGH_VALUE_FIELDS = {
    "ecommerce_detail": frozenset(
        {"description", "product_details", "additional_images", "specifications"}
    ),
    "job_detail": frozenset({"description", "qualifications", "responsibilities"}),
}
DOM_OPTIONAL_CUE_FIELDS = {
    "ecommerce_detail": frozenset({"care", "dimensions", "features", "materials"}),
    "job_detail": frozenset({"benefits", "requirements", "skills"}),
}
ECOMMERCE_DETAIL_DEFAULT_CONTRACT_FIELDS = (
    "title",
    "url",
    "brand",
    "description",
    "image_url",
)
ECOMMERCE_DETAIL_SELLABLE_OFFER_FIELDS = ("price", "currency")
ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD = "availability"
SURFACE_BROWSER_RETRY_TARGETS = {
    "ecommerce_detail": ("price", "currency", "title", "image_url")
}
SURFACE_ACQUISITION_CONTRACT_FIELDS = {
    "ecommerce_detail": ("title", "price", "image_url")
}
SURFACE_FIELD_REPAIR_TARGETS = {
    "ecommerce_detail": (
        *ECOMMERCE_DETAIL_DEFAULT_CONTRACT_FIELDS,
        *ECOMMERCE_DETAIL_SELLABLE_OFFER_FIELDS,
        ECOMMERCE_DETAIL_EXPOSED_AVAILABILITY_FIELD,
    )
}
ECOMMERCE_DETAIL_JS_STATE_PRIORITY_FIELDS = frozenset(
    {
        "variants",
        "price",
        "currency",
        "original_price",
        "sku",
        "title",
        "availability",
        "brand",
        "image_url",
        "size",
        "color",
        "stock_quantity",
    }
)
ECOMMERCE_DETAIL_FIELD_FACT_TYPES = {
    "availability": OFFER_AVAILABILITY_FACT_TYPE,
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "category": "product.category",
    "currency": OFFER_CURRENCY_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "gtin": PRODUCT_GTIN_FACT_TYPE,
    "image": ASSET_IMAGE_URL_FACT_TYPE,
    "image_url": ASSET_IMAGE_URL_FACT_TYPE,
    "mpn": PRODUCT_MPN_FACT_TYPE,
    "name": PRODUCT_TITLE_FACT_TYPE,
    "original_price": "offer.original_price",
    "price": OFFER_PRICE_FACT_TYPE,
    "sku": PRODUCT_SKU_FACT_TYPE,
    "title": PRODUCT_TITLE_FACT_TYPE,
    "url": PRODUCT_URL_FACT_TYPE,
}
ECOMMERCE_PUBLIC_FIELD_FACT_TYPES = {
    "title": PRODUCT_TITLE_FACT_TYPE,
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "sku": PRODUCT_SKU_FACT_TYPE,
    "price": OFFER_PRICE_FACT_TYPE,
    "currency": OFFER_CURRENCY_FACT_TYPE,
    "availability": OFFER_AVAILABILITY_FACT_TYPE,
    "image_url": ASSET_IMAGE_URL_FACT_TYPE,
}
ECOMMERCE_TYPED_STRING_FACT_TYPES = frozenset(
    {
        ASSET_IMAGE_URL_FACT_TYPE,
        OFFER_AVAILABILITY_FACT_TYPE,
        OFFER_CURRENCY_FACT_TYPE,
        PRODUCT_BRAND_FACT_TYPE,
        "product.category",
        PRODUCT_DESCRIPTION_FACT_TYPE,
        PRODUCT_GTIN_FACT_TYPE,
        PRODUCT_MPN_FACT_TYPE,
        PRODUCT_SKU_FACT_TYPE,
        PRODUCT_TITLE_FACT_TYPE,
        PRODUCT_URL_FACT_TYPE,
        VARIANT_GTIN_FACT_TYPE,
        "variant.id",
        VARIANT_SKU_FACT_TYPE,
        "variant.url",
    }
)
# Integer identifier fact types are a strict subset of the typed string facts.
# They receive special int-to-str conversion before general string validation.
ECOMMERCE_INTEGER_IDENTIFIER_FACT_TYPES = frozenset(
    {
        PRODUCT_GTIN_FACT_TYPE,
        PRODUCT_MPN_FACT_TYPE,
        PRODUCT_SKU_FACT_TYPE,
        VARIANT_GTIN_FACT_TYPE,
        "variant.id",
        VARIANT_SKU_FACT_TYPE,
    }
)
INVALID_SCALAR_TYPE_EVIDENCE_FLAG = "invalid_scalar_type"
ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES = {
    **dict.fromkeys(DETAIL_EXPLICIT_MINOR_UNIT_PRICE_FIELDS, OFFER_PRICE_FACT_TYPE),
    **dict.fromkeys(ECOMMERCE_DISPLAY_PRICE_SOURCE_KEYS, OFFER_PRICE_FACT_TYPE),
    "availability": OFFER_AVAILABILITY_FACT_TYPE,
    "available": OFFER_AVAILABILITY_FACT_TYPE,
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "brandName": PRODUCT_BRAND_FACT_TYPE,
    "brand_label": PRODUCT_BRAND_FACT_TYPE,
    "brandLabel": PRODUCT_BRAND_FACT_TYPE,
    "currency": OFFER_CURRENCY_FACT_TYPE,
    "currencyCode": OFFER_CURRENCY_FACT_TYPE,
    "currentPrice": OFFER_PRICE_FACT_TYPE,
    "current_price": OFFER_PRICE_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "image": ASSET_IMAGE_URL_FACT_TYPE,
    "imageUrl": ASSET_IMAGE_URL_FACT_TYPE,
    "images": ASSET_IMAGE_URL_FACT_TYPE,
    "inStock": OFFER_AVAILABILITY_FACT_TYPE,
    "manufacturer": PRODUCT_BRAND_FACT_TYPE,
    "manufacturer_name": PRODUCT_BRAND_FACT_TYPE,
    "manufacturerName": PRODUCT_BRAND_FACT_TYPE,
    "designer": PRODUCT_BRAND_FACT_TYPE,
    "designer_name": PRODUCT_BRAND_FACT_TYPE,
    "designerName": PRODUCT_BRAND_FACT_TYPE,
    "vendor": PRODUCT_BRAND_FACT_TYPE,
    "name": PRODUCT_TITLE_FACT_TYPE,
    "price": OFFER_PRICE_FACT_TYPE,
    "productDescription": PRODUCT_DESCRIPTION_FACT_TYPE,
    "productName": PRODUCT_TITLE_FACT_TYPE,
    "sku": PRODUCT_SKU_FACT_TYPE,
    "title": PRODUCT_TITLE_FACT_TYPE,
    "url": PRODUCT_URL_FACT_TYPE,
}
ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS = (
    "productId",
    "productID",
    "product_id",
    "productCode",
    "product_code",
)
ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS = frozenset(
    {
        "brand",
        "brandName",
        "brand_label",
        "brandLabel",
        "description",
        "image",
        "imageUrl",
        "images",
        "manufacturer",
        "manufacturer_name",
        "manufacturerName",
        "designer",
        "designer_name",
        "designerName",
        "vendor",
        "name",
        "productDescription",
        "productName",
        "sku",
        "title",
        "url",
    }
)
ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS = frozenset(
    {"offer", "offers", "price", "prices", "pricing", "variant", "variants"}
)
ECOMMERCE_IMAGE_SOURCE_KEYS = frozenset({"image", "imageUrl", "images"})
ECOMMERCE_MICRODATA_FACT_TYPES = {
    "availability": OFFER_AVAILABILITY_FACT_TYPE,
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "image": ASSET_IMAGE_URL_FACT_TYPE,
    "name": PRODUCT_TITLE_FACT_TYPE,
    "price": OFFER_PRICE_FACT_TYPE,
    "priceCurrency": OFFER_CURRENCY_FACT_TYPE,
    "sku": PRODUCT_SKU_FACT_TYPE,
}
ECOMMERCE_OPENGRAPH_FACT_TYPES = {
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "og:description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "og:image": ASSET_IMAGE_URL_FACT_TYPE,
    "og:title": PRODUCT_TITLE_FACT_TYPE,
    "og:url": PRODUCT_URL_FACT_TYPE,
    "product:brand": PRODUCT_BRAND_FACT_TYPE,
    "product:price:amount": OFFER_PRICE_FACT_TYPE,
    "product:price:currency": OFFER_CURRENCY_FACT_TYPE,
    "twitter:description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "twitter:image": ASSET_IMAGE_URL_FACT_TYPE,
    "twitter:title": PRODUCT_TITLE_FACT_TYPE,
}
ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES = {
    "brand": PRODUCT_BRAND_FACT_TYPE,
    "description": PRODUCT_DESCRIPTION_FACT_TYPE,
    "gtin": PRODUCT_GTIN_FACT_TYPE,
    "manufacturer": PRODUCT_BRAND_FACT_TYPE,
    "manufacturerName": PRODUCT_BRAND_FACT_TYPE,
    "designer": PRODUCT_BRAND_FACT_TYPE,
    "mpn": PRODUCT_MPN_FACT_TYPE,
    "name": PRODUCT_TITLE_FACT_TYPE,
    "sku": PRODUCT_SKU_FACT_TYPE,
    "url": PRODUCT_URL_FACT_TYPE,
}
ECOMMERCE_JSONLD_OFFER_FACT_TYPES = {
    "availability": OFFER_AVAILABILITY_FACT_TYPE,
    "lowPrice": OFFER_PRICE_FACT_TYPE,
    "price": OFFER_PRICE_FACT_TYPE,
    "priceCurrency": OFFER_CURRENCY_FACT_TYPE,
    "seller": "offer.seller",
}
ECOMMERCE_JSONLD_VARIANT_FACT_TYPES = {
    "sku": VARIANT_SKU_FACT_TYPE,
    "gtin": VARIANT_GTIN_FACT_TYPE,
    "url": "variant.url",
    "color": "variant.option.color",
    "size": "variant.option.size",
}
REQUESTED_FIELD_DOM_SELECTOR_TEMPLATES = (
    '[itemprop="{field}"]',
    '[data-field="{field}"]',
    '[data-field-name="{field}"]',
    ".{field}",
    ".{dash_field}",
)

TITLE_STRUCTURED_VALUE_KEYS = ("values", "title", "name", "label", "text", "value")
PRICE_DICT_PREFERRED_KEYS = (
    "formattedPrice",
    "displayPrice",
    "price",
    "amount",
    "currentValue",
    "lowPrice",
    "minPrice",
    "highPrice",
    "value",
)
UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
ECOMMERCE_SURFACE_EXTRA_ALIASES = {
    "capacity": (
        "capacity_l",
        "capacity_liter",
        "capacity_litre",
        "capacity_liters",
        "capacity_litres",
    ),
    "energy_rating": ("energy_rating", "energy_star_rating", "star_rating"),
}
JOB_SURFACE_EXTRA_ALIASES = {
    "job_type": ("type", "employment_type", "commitment", "work_type")
}
ECOMMERCE_CATEGORY_ALIAS_REMOVALS = frozenset({"type", "job_type", "employment_type"})
ECOMMERCE_CATEGORY_ALIAS_ADDITIONS = ("product_type",)
VARIANT_AXIS_FIELD_NAMES = (
    COLOR_FIELD,
    SIZE_FIELD,
    "type",
    "fit",
    "style",
    "material",
    "finish",
    "pattern",
    "capacity",
    WIDTH_FIELD,
)
REQUESTED_FIELD_PREFIXES = ("product_", "item_", "job_")
HTML_SECTION_FIELDS = frozenset(
    {"responsibilities", "qualifications", "benefits", "skills"}
)
REQUESTED_FIELD_ALIAS_BASES = {
    key: FIELD_ALIASES.get(key, [])
    for key in (
        "responsibilities",
        "qualifications",
        "benefits",
        "skills",
        "summary",
        "specifications",
        "product_details",
        "features",
        "materials",
        "care",
        "dimensions",
        "remote",
        "requirements",
        "gender",
    )
}
REQUESTED_FIELD_ALIAS_EXTRAS = {
    "responsibilities": (
        "job responsibilities",
        "key responsibilities",
        "what you'll do",
    ),
    "qualifications": (
        "job qualifications",
        "should have",
        "minimum requirements",
        "who you are",
    ),
    "benefits": ("job benefits", "perks", "what we offer"),
    "skills": ("job skills", "experience", "what you'll bring"),
    "summary": ("description", "about the role", "about the team"),
    "specifications": ("specs", "technical details"),
    "features": ("key features",),
    "materials": ("fabrics", "material composition"),
    "care": ("care instructions",),
}


def __getattr__(name: str) -> Any:
    raise AttributeError(name)


__all__ = sorted(name for name in globals() if name.isupper())
