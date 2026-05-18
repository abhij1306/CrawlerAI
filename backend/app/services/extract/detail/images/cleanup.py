from __future__ import annotations

__all__ = (
    "backfill_parent_image_from_variants",
    "sanitize_detail_images",
    "backfill_detail_image_from_html",
    "detail_image_matches_primary_family",
)

import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse


from app.services.config.extraction_rules import (
    IMAGE_FAMILY_NOISE_TOKENS,
    IMAGE_PATH_TOKENS,
)
from app.services.shared.field_coerce import (
    absolute_url,
    clean_text,
    extract_urls,
    text_or_none,
)
from app.services.field_url_normalization import same_site
from app.services.dom.selector_engine import (
    dedupe_image_urls,
    upgrade_low_resolution_image_url,
)
from app.services.extract.detail.identity.core import (
    detail_identity_codes_match,
    detail_identity_codes_from_record_fields as _detail_identity_codes_from_record_fields,
    detail_identity_codes_from_url as _detail_identity_codes_from_url,
    detail_identity_tokens as _detail_identity_tokens,
    detail_title_from_url as _detail_title_from_url,
    detail_url_looks_like_product as _detail_url_looks_like_product,
    semantic_detail_identity_tokens as _semantic_detail_identity_tokens,
)
from app.services.config.detail_extraction_constants import (
    NON_PRODUCT_IMAGE_HINTS_LOWER as _NON_PRODUCT_IMAGE_HINTS_LOWER,
    PLACEHOLDER_IMAGE_URL_PATTERNS_LOWER as _PLACEHOLDER_IMAGE_URL_PATTERNS_LOWER,
)

logger = logging.getLogger(__name__)


def backfill_parent_image_from_variants(record: dict[str, Any]) -> None:
    if text_or_none(record.get("image_url")):
        return
    for variant in list(record.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        image_url = text_or_none(variant.get("image_url"))
        if image_url:
            record["image_url"] = image_url
            return


def _sanitize_detail_images(record: dict[str, Any], *, identity_url: str) -> None:
    raw_images = [
        text_or_none(record.get("image_url")),
        *[text_or_none(value) for value in list(record.get("additional_images") or [])],
    ]
    images = [upgrade_low_resolution_image_url(image) for image in raw_images if image]
    if not images:
        return
    cleaned: list[str] = []
    for image in images:
        normalized_image = (
            "https://" + image[7:] if image.lower().startswith("http://") else image
        )
        if not _detail_image_candidate_is_usable(
            normalized_image, identity_url=identity_url
        ):
            continue
        cleaned.append(normalized_image)
    if not cleaned:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    primary_image = cleaned[0]
    family_cleaned: list[str] = []
    for normalized_image in cleaned:
        if not detail_image_matches_primary_family(
            normalized_image,
            primary_image=primary_image,
            title=record.get("title"),
        ):
            continue
        family_cleaned.append(normalized_image)
    merged = dedupe_image_urls(family_cleaned) or _dedupe_cleaned_detail_images(
        family_cleaned
    )
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
    else:
        record.pop("additional_images", None)


def sanitize_detail_images(record: dict[str, Any], *, identity_url: str) -> None:
    _sanitize_detail_images(record, identity_url=identity_url)


def _backfill_detail_image_from_html(
    record: dict[str, Any],
    *,
    soup: Any,
    identity_url: str,
) -> None:
    if text_or_none(record.get("image_url")):
        return
    candidates: list[str] = []
    for node in soup.select(
        "meta[property='og:image'], meta[name='twitter:image'], "
        "link[rel='preload'][as='image'], main img, [role='main'] img"
    ):
        raw = node.get("content") or node.get("href") or node.get("src")
        if not raw:
            continue
        urls = extract_urls(raw, identity_url)
        candidates.extend(urls or [absolute_url(identity_url, raw)])
    for url in _dedupe_cleaned_detail_images(candidates):
        if _detail_image_candidate_is_usable(url, identity_url=identity_url):
            record["image_url"] = url
            field_sources = record.setdefault("_field_sources", {})
            if isinstance(field_sources, dict):
                field_sources.setdefault("image_url", []).append("html_image")
            return


def backfill_detail_image_from_html(
    record: dict[str, Any],
    *,
    soup: Any,
    identity_url: str,
) -> None:
    _backfill_detail_image_from_html(record, soup=soup, identity_url=identity_url)


def _dedupe_cleaned_detail_images(urls: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for url in urls:
        cleaned = text_or_none(url)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged


def _detail_image_candidate_is_usable(url: str, *, identity_url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = str(parsed.path or "").strip()
    if not path or path == "/":
        return False
    lowered = url.lower()
    if "base64," in lowered or lowered.startswith("data:"):
        return False
    if any(pattern in lowered for pattern in _PLACEHOLDER_IMAGE_URL_PATTERNS_LOWER):
        return False
    if any(pattern in lowered for pattern in _NON_PRODUCT_IMAGE_HINTS_LOWER):
        return False
    if _detail_image_url_is_extensionless_transform(path):
        return False
    if (
        same_site(identity_url, url)
        and _detail_url_looks_like_product(url)
        and not _detail_path_looks_like_image_asset(path, lowered)
    ):
        return False
    if re.search(r"/products?/[\d?=&-]*$", lowered):
        return False
    candidate_title = _detail_image_title_from_url(url)
    if (
        candidate_title
        and _detail_image_title_has_identity_signal(candidate_title)
        and not (
            (candidate_codes := _detail_identity_codes_from_url(url))
            and detail_identity_codes_match(
                _detail_identity_codes_from_url(identity_url), candidate_codes
            )
        )
        and not _detail_image_title_matches_requested_identity(
            candidate_title,
            requested_page_url=identity_url,
        )
    ):
        return False
    return True


def _detail_image_url_is_extensionless_transform(path: str) -> bool:
    filename = unquote(str(path or "").rsplit("/", 1)[-1])
    if re.search(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)$", filename, re.I):
        return False
    return re.search(r"\._[A-Z]+_[A-Z]{2}\d+\s*$", filename, re.I) is not None


def _detail_path_looks_like_image_asset(path: str, lowered_url: str) -> bool:
    lowered_path = str(path or "").lower()
    if re.search(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)(?:$|\?)", lowered_url):
        return True
    return any(token in lowered_path for token in IMAGE_PATH_TOKENS)


def detail_image_matches_primary_family(
    url: str,
    *,
    primary_image: str,
    title: object,
) -> bool:
    if url == primary_image:
        return True
    primary_tokens = _detail_image_family_tokens(primary_image)
    candidate_tokens = _detail_image_family_tokens(url)
    if primary_tokens and candidate_tokens and primary_tokens & candidate_tokens:
        return True
    title_tokens = _semantic_detail_identity_tokens(title)
    if (
        title_tokens
        and candidate_tokens
        and len(title_tokens & candidate_tokens) >= min(2, len(title_tokens))
    ):
        return True
    primary_code = _detail_image_media_code(primary_image)
    candidate_code = _detail_image_media_code(url)
    if primary_code and candidate_code and primary_code == candidate_code:
        return True
    return not primary_tokens and not title_tokens


def _detail_image_title_from_url(url: str) -> str | None:
    path = unquote(urlparse(url).path)
    filename = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.(?:avif|gif|jpe?g|png|svg|tiff?|webp)$", "", filename, flags=re.I)
    if not stem or re.fullmatch(r"img\d+", stem, re.I):
        return None
    if _detail_image_stem_looks_encoded(stem):
        return None
    normalized = clean_text(
        re.sub(
            r"[_-]+",
            " ",
            re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem),
        )
    )
    return normalized or None


def _detail_image_stem_looks_encoded(stem: str) -> bool:
    compact = re.sub(r"[^A-Za-z0-9_-]+", "", str(stem or ""))
    alpha = re.sub(r"[^A-Za-z]+", "", compact)
    if (
        6 <= len(compact) < 24
        and re.search(r"[A-Z]", compact)
        and re.search(r"[a-z]", compact)
        and not re.search(r"[aeiou]{2,}", alpha, re.I)
    ):
        return True
    if len(compact) < 24:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]+", compact):
        return False
    if not (re.search(r"[A-Z]", compact) and re.search(r"[a-z]", compact)):
        return False
    return (
        len(re.findall(r"[A-Z]", compact)) >= 3 and len(re.findall(r"\d", compact)) >= 2
    )


def _detail_image_title_has_identity_signal(title: str) -> bool:
    return bool(
        len(_semantic_detail_identity_tokens(title)) >= 2
        or _detail_identity_codes_from_record_fields({"title": title})
    )


def _detail_image_title_matches_requested_identity(
    title: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_record_fields({"title": title})
    if (
        requested_codes
        and candidate_codes
        and detail_identity_codes_match(requested_codes, candidate_codes)
    ):
        return True
    requested_title = _detail_title_from_url(requested_page_url)
    normalized_requested_title = clean_text(requested_title)
    normalized_candidate_title = clean_text(title)
    if (
        normalized_requested_title
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(
            normalized_requested_title.lower()
        )
    ):
        return True
    requested_path = str(urlparse(requested_page_url).path or "")
    requested_segments = [
        clean_text(re.sub(r"[_-]+", " ", segment))
        for segment in requested_path.split("/")
        if clean_text(re.sub(r"[_-]+", " ", segment))
    ]
    requested_slug = next(
        (
            segment
            for segment in reversed(requested_segments)
            if segment.lower() not in {"product", "products", "p", "pd", "dp"}
        ),
        "",
    )
    if (
        requested_slug
        and normalized_candidate_title
        and normalized_candidate_title.lower().startswith(requested_slug.lower())
    ):
        return True
    requested_tokens = _detail_identity_tokens(requested_title or requested_page_url)
    candidate_tokens = _detail_identity_tokens(title)
    if not requested_tokens or not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    minimum_overlap = 2 if min(len(requested_tokens), len(candidate_tokens)) <= 4 else 4
    return len(overlap) >= min(minimum_overlap, len(requested_tokens))


def _detail_image_family_tokens(url: str) -> set[str]:
    parts = [
        segment
        for segment in re.split(r"[^a-z0-9]+", unquote(urlparse(url).path).lower())
        if len(segment) >= 4
    ]
    return {part for part in parts if part not in IMAGE_FAMILY_NOISE_TOKENS}


def _detail_image_media_code(url: str) -> str | None:
    match = re.search(r"/([a-z]\d{5,})/", urlparse(url).path.lower())
    if match is not None:
        return match.group(1)
    return None
