"""URL coercion and tracking-cleanup helpers for field shaping."""
from __future__ import annotations

from app.services.config.extraction_rules import IMAGE_FIELDS, URL_FIELDS
from app.services.config.field_mappings import ADDITIONAL_IMAGES_FIELD
from app.services.field_url_normalization import (
    strip_record_tracking_params as strip_record_tracking_params,
    strip_tracking_query_params as strip_tracking_query_params,
)
from app.services.shared.url_utils import (
    absolute_url as absolute_url,
    extract_urls,
    same_host as same_host,
)


def coerce_url_field_value(field_name: str, value: object, page_url: str) -> object | None:
    urls = extract_urls(value, page_url)
    if field_name == ADDITIONAL_IMAGES_FIELD:
        return urls or None
    return urls[0] if urls else None


def is_url_field(field_name: str) -> bool:
    return field_name in URL_FIELDS or field_name in IMAGE_FIELDS


__all__ = [
    "absolute_url",
    "coerce_url_field_value",
    "extract_urls",
    "is_url_field",
    "same_host",
    "strip_record_tracking_params",
    "strip_tracking_query_params",
]
