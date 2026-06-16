from __future__ import annotations

__all__ = (
    "_materialize_image_fields",
)

import logging
from collections.abc import Callable

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES,
)
from app.services.dom.selector_engine import dedupe_image_urls, extract_page_images
from app.services.extract.contracts import CandidateSet
from app.services.shared.field_coerce import text_or_none

logger = logging.getLogger(__name__)


def _materialize_image_fields(
    *,
    surface: str,
    candidate_set: CandidateSet,
    source_rank: Callable[[str, str, str | None], int],
    page_url: str,
    soup: BeautifulSoup | None = None,
    raw_soup: BeautifulSoup | None = None,
) -> tuple[list[str], str | None]:
    values: list[str] = []
    primary_source: str | None = None
    ordered_candidates = [
        *candidate_set.ordered(
            "image_url",
            source_rank=lambda source: source_rank(surface, "image_url", source),
        ),
        *candidate_set.ordered(
            "additional_images",
            source_rank=lambda source: source_rank(
                surface,
                "additional_images",
                source,
            ),
        ),
    ]
    for candidate in ordered_candidates:
        if primary_source is None and candidate.source:
            primary_source = candidate.source
        raw_value = candidate.value
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
