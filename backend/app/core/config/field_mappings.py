"""Code-owned field names and aliases for the four explicit surfaces."""

from __future__ import annotations

import re
from typing import Any

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
    "brand": ["brand", "manufacturer", "manufacturer_name", "brand_name", "designer"],
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
    "run_diagnosis": {
        "response_type": "object",
        "system_file": "run_diagnosis.system.txt",
        "user_file": "run_diagnosis.user.txt",
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
SURFACE_BROWSER_RETRY_TARGETS = {
    "ecommerce_detail": ("price", "currency", "title", "image_url")
}
SURFACE_FIELD_REPAIR_TARGETS = {"ecommerce_detail": ("price", "title", "image_url")}
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
    "availability": "offer.availability",
    "brand": "product.brand",
    "category": "product.category",
    "currency": "offer.currency",
    "description": "product.description",
    "gtin": "product.gtin",
    "image": "asset.image_url",
    "image_url": "asset.image_url",
    "mpn": "product.mpn",
    "name": "product.title",
    "original_price": "offer.original_price",
    "price": "offer.price",
    "sku": "product.sku",
    "title": "product.title",
    "url": "product.url",
}
ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES = {
    "availability": "offer.availability",
    "available": "offer.availability",
    "brand": "product.brand",
    "brandName": "product.brand",
    "currency": "offer.currency",
    "currencyCode": "offer.currency",
    "description": "product.description",
    "image": "asset.image_url",
    "imageUrl": "asset.image_url",
    "images": "asset.image_url",
    "inStock": "offer.availability",
    "manufacturer": "product.brand",
    "name": "product.title",
    "price": "offer.price",
    "productDescription": "product.description",
    "productName": "product.title",
    "sku": "product.sku",
    "title": "product.title",
    "url": "product.url",
}
ECOMMERCE_PRODUCT_CONTEXT_SOURCE_KEYS = frozenset(
    {
        "brand",
        "brandName",
        "description",
        "image",
        "imageUrl",
        "images",
        "manufacturer",
        "name",
        "productDescription",
        "productName",
        "sku",
        "title",
        "url",
    }
)
ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS = frozenset(
    {"offer", "offers", "pricing", "product", "products", "variant", "variants"}
)
ECOMMERCE_IMAGE_SOURCE_KEYS = frozenset({"image", "imageUrl", "images"})
ECOMMERCE_MICRODATA_FACT_TYPES = {
    "availability": "offer.availability",
    "brand": "product.brand",
    "description": "product.description",
    "image": "asset.image_url",
    "name": "product.title",
    "price": "offer.price",
    "priceCurrency": "offer.currency",
    "sku": "product.sku",
}
ECOMMERCE_OPENGRAPH_FACT_TYPES = {
    "og:description": "product.description",
    "og:image": "asset.image_url",
    "og:title": "product.title",
    "og:url": "product.url",
    "product:brand": "product.brand",
    "product:price:amount": "offer.price",
    "product:price:currency": "offer.currency",
}
ECOMMERCE_JSONLD_PRODUCT_FACT_TYPES = {
    "brand": "product.brand",
    "description": "product.description",
    "gtin": "product.gtin",
    "manufacturer": "product.brand",
    "mpn": "product.mpn",
    "name": "product.title",
    "sku": "product.sku",
    "url": "product.url",
}
ECOMMERCE_JSONLD_OFFER_FACT_TYPES = {
    "availability": "offer.availability",
    "lowPrice": "offer.price",
    "price": "offer.price",
    "priceCurrency": "offer.currency",
    "seller": "offer.seller",
}
ECOMMERCE_JSONLD_VARIANT_FACT_TYPES = {
    "sku": "variant.sku",
    "gtin": "variant.gtin",
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
