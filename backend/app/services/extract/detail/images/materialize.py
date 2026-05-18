from __future__ import annotations

__all__ = (
    "_SOURCE_PRIORITY_RANK",
    "_ordered_candidates_for_field",
    "_materialize_image_fields",
)

import logging
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES,
    SOURCE_PRIORITY,
)
from app.services.dom.selector_engine import dedupe_image_urls, extract_page_images
from app.services.shared.field_coerce import text_or_none

_SOURCE_PRIORITY_RANK = {
    source_name: index for index, source_name in enumerate(SOURCE_PRIORITY)
}
logger = logging.getLogger(__name__)


def _ordered_candidates_for_field(
    surface: str,
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    values = list(candidates.get(field_name) or [])
    sources = list(candidate_sources.get(field_name) or [])
    rows: list[tuple[int, int, str | None, object]] = []
    for index, raw_value in enumerate(values):
        source = sources[index] if index < len(sources) else None
        source_rank = 100 + _SOURCE_PRIORITY_RANK.get(
            str(source or ""), len(_SOURCE_PRIORITY_RANK)
        )
        rows.append((source_rank, index, source, raw_value))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [(source, raw_value) for _, _, source, raw_value in rows]

def _materialize_image_fields(
    *,
    surface: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    page_url: str,
    soup: BeautifulSoup | None = None,
    raw_soup: BeautifulSoup | None = None,
) -> tuple[list[str], str | None]:
    values: list[str] = []
    primary_source: str | None = None
    ordered_candidates = [
        *_ordered_candidates_for_field(
            surface, "image_url", candidates, candidate_sources
        ),
        *_ordered_candidates_for_field(
            surface, "additional_images", candidates, candidate_sources
        ),
    ]
    for source, raw_value in ordered_candidates:
        if primary_source is None and source:
            primary_source = source
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in items:
            image = text_or_none(item)
            if image:
                values.append(image)
    images = dedupe_image_urls(values)
    try:
        parsed_max_winning_images = int(
            DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES
        )
    except (TypeError, ValueError):
        logger.error(
            "Invalid DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES=%r; using 1",
            DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES,
        )
        parsed_max_winning_images = 1
    if (
        str(surface or "").strip().lower() == "ecommerce_detail"
        and raw_soup is not None
        and len(images) <= parsed_max_winning_images
    ):
        soup_img_count = len(soup.find_all("img")) if soup is not None else 0
        if len(raw_soup.find_all("img")) > soup_img_count:
            images = dedupe_image_urls(
                [*images, *extract_page_images(raw_soup, page_url, surface=surface)]
            )
            primary_source = primary_source or "dom_selector"
    return images, primary_source
