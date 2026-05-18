from __future__ import annotations

__all__ = (
    "title_from_url",
    "same_url_anchor_text_candidates",
    "extract_price_signal_from_card",
    "card_title_node",
    "card_title_score",
    "select_primary_anchor",
    "select_primary_card_url",
    "extract_page_images_from_node",
    "extract_image_title_hint",
    "should_replace_title_with_image_hint",
    "normalize_listing_title",
    "title_token_overlap",
    "extract_label_value_pairs_from_node",
    "extract_brand_signal_from_card",
)

import re
from urllib.parse import urlsplit

from selectolax.lexbor import SelectolaxError

from app.services.config.extraction_rules import (
    EXTRACTION_RULES,
    LISTING_BRAND_MAX_WORDS,
    LISTING_BRAND_SELECTORS,
    LISTING_CARD_URL_ATTRS,
    LISTING_LABEL_NOISE_TOKENS,
    LISTING_PRICE_NODE_SELECTORS,
    LISTING_PROMINENT_TITLE_TAGS,
    LISTING_STRUCTURE_NEGATIVE_HINTS,
    NON_PRODUCT_IMAGE_HINTS,
    NON_PRODUCT_PROVIDER_HINTS,
    TITLE_PROMOTION_PREFIXES,
)
from app.services.extract.detail.identity.core import (
    listing_detail_like_path,
    listing_url_is_structural,
)
from app.services.extract.listing_card_fragments import (
    listing_node_attr,
    listing_node_css,
    listing_node_html,
    listing_node_signature,
    listing_node_tag,
    listing_node_text,
)
from app.services.field_url_normalization import same_site
from app.services.shared.field_coerce import (
    PRICE_RE,
    absolute_url,
    clean_text,
    extract_currency_code,
    extract_price_text,
    is_title_noise,
    same_host,
)

_LISTING_STRUCTURE_NEGATIVE_HINTS = frozenset(LISTING_STRUCTURE_NEGATIVE_HINTS)


def _title_from_url(url: str) -> str | None:
    path = str(urlsplit(str(url or "")).path or "").strip("/")
    if not path:
        return None
    terminal = path.rsplit("/", 1)[-1]
    terminal = re.sub(r"\.(html?|htm)$", "", terminal, flags=re.I)
    if not terminal:
        return None
    title = clean_text(re.sub(r"[-_]+", " ", terminal))
    if not title or title.isdigit():
        return None
    return title


def _same_url_anchor_text_candidates(card, url: str) -> list[str]:
    if not url:
        return []
    texts: list[str] = []
    seen: set[str] = set()
    for link in listing_node_css(card, "a[href]"):
        href = listing_node_attr(link, "href")
        if not href or absolute_url(url, href) != url:
            continue
        text = clean_text(listing_node_attr(link, "title") or listing_node_text(link))
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def _extract_price_signal_from_card(card) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for selector in LISTING_PRICE_NODE_SELECTORS:
        for node in listing_node_css(card, selector):
            order += 1
            raw_text = clean_text(
                listing_node_attr(node, "content")
                or listing_node_attr(node, "data-price")
                or listing_node_attr(node, "aria-label")
                or listing_node_text(node)
            )
            if not raw_text or len(raw_text) > 120:
                continue
            price_text = extract_price_text(
                raw_text,
                prefer_last=False,
                allow_unmarked=True,
            )
            if not price_text:
                continue
            score = 0
            attrs = listing_node_signature(node)
            if "price" in attrs:
                score += 5
            lowered_raw_text = raw_text.lower()
            if any(
                token in attrs or token in lowered_raw_text for token in ("sale", "now")
            ):
                score += 4
            if any(
                token in attrs or token in lowered_raw_text
                for token in ("regular", "original", "mrp", "list")
            ):
                score -= 6
            if len(raw_text) <= 40:
                score += 2
            if extract_currency_code(price_text):
                score += 2
            candidates.append((score, order, price_text))
    if candidates:
        candidates.sort(key=lambda row: (-row[0], row[1]))
        return candidates[0][2]
    card_text = listing_node_text(card)
    fallback_price = extract_price_text(card_text, prefer_last=True)
    if not fallback_price:
        return None
    lowered_card_text = card_text.lower()
    if any(symbol in card_text for symbol in ("$", "£", "€", "₹")):
        return fallback_price
    if re.search(r"\b(?:usd|eur|gbp|inr|cad|aud|jpy|zar|aed)\b", lowered_card_text):
        return fallback_price
    if re.search(r"\b(?:price|sale|from|now|only|msrp|mrp)\b", lowered_card_text):
        return fallback_price
    return None


def _card_title_node(card) -> object | None:
    candidates: list[object] = []
    listing_extraction = EXTRACTION_RULES.get("listing_extraction")
    listing_extraction_map = (
        listing_extraction if isinstance(listing_extraction, dict) else {}
    )
    selectors = listing_extraction_map.get("card_title_selectors")
    selector_values = selectors if isinstance(selectors, list) else []
    for selector in selector_values:
        candidates.extend(listing_node_css(card, str(selector)))
    if candidates:
        best = max(
            candidates,
            key=lambda node: (_card_title_score(node), len(listing_node_text(node))),
        )
        if _card_title_score(best) > 0:
            return best
    fallback_candidates = _fallback_card_title_candidates(card)
    if fallback_candidates:
        best = max(
            fallback_candidates,
            key=lambda node: (_card_title_score(node), len(listing_node_text(node))),
        )
        if _card_title_score(best) > 0:
            return best
    anchors = listing_node_css(card, "a[href]")
    if not anchors:
        return None
    best = max(anchors, key=_card_title_score)
    return best if _card_title_score(best) > 0 else None


def _card_title_score(
    node=None,
    *,
    text: str | None = None,
    attrs: str | None = None,
    tag_name: str | None = None,
    href_present: bool | None = None,
) -> int:
    if node is not None:
        text = listing_node_text(node)
        attrs = listing_node_signature(node)
        tag_name = listing_node_tag(node)
        href_present = bool(listing_node_attr(node, "href"))
    text = clean_text(text)
    if not text:
        return -100
    attrs = str(attrs or "")
    tag_name = str(tag_name or "")
    href_present = bool(href_present)
    score = 0
    if any(
        token in attrs
        for token in (
            "title",
            "name",
            "product",
            "item",
            "listing",
            "result",
            "job",
            "record",
            "release",
        )
    ):
        score += 6
    if any(
        token in attrs
        for token in (
            "brand",
            "seller",
            "vendor",
            "rating",
            "price",
            "size",
            "wishlist",
        )
    ):
        score -= 6
    if tag_name in {"h1", "h2", "h3", "h4", "h5", "a", "strong", "b"}:
        score += 2
    if text.isdigit():
        score -= 20
    if re.search(r"[a-z]", text, flags=re.I):
        score += 2
    text_len = len(text)
    if 8 <= text_len <= 180:
        score += 3
    elif text_len < 4:
        score -= 6
    elif text_len > 220:
        score -= 2
    if is_title_noise(text):
        score -= 4
    if href_present:
        score += 2
    return score


def _fallback_card_title_candidates(card) -> list[object]:
    candidates: list[object] = []
    for node in listing_node_css(card, "*"):
        tag_name = listing_node_tag(node)
        if tag_name in {"a", "button"}:
            continue
        text = listing_node_text(node)
        if not text or len(text) > 220:
            continue
        lowered_text = text.lower()
        if PRICE_RE.search(text):
            continue
        if any(
            token in lowered_text for token in ("add to bag", "add to cart", "wishlist")
        ):
            continue
        if tag_name in LISTING_PROMINENT_TITLE_TAGS:
            candidates.append(node)
            continue
        attrs = listing_node_signature(node)
        if not attrs:
            continue
        if not any(token in attrs for token in ("title", "name", "product", "item")):
            continue
        candidates.append(node)
    return candidates


def _select_primary_anchor(
    card,
    page_url: str,
    *,
    surface: str,
    title_node=None,
) -> tuple[object, str, str, int] | None:
    is_job = surface.startswith("job_")
    is_article = surface == "article_listing"
    card_html = listing_node_html(card)
    title_index = -1
    if title_node is not None and listing_node_tag(title_node) != "a":
        title_html = listing_node_html(title_node)
        if card_html and title_html:
            title_index = card_html.find(title_html)
    best: tuple[int, object, str, str] | None = None
    anchors = []
    if listing_node_attr(card, "href"):
        anchors.append(card)
    anchors.extend(listing_node_css(card, "a[href]"))
    for anchor in anchors:
        url = absolute_url(page_url, listing_node_attr(anchor, "href"))
        if not url or (not same_host(page_url, url) and not same_site(page_url, url)):
            continue
        lowered_url = url.lower()
        if not is_article and listing_url_is_structural(url, page_url):
            continue
        if any(
            token in lowered_url
            for token in ("sort=", "filter=", "facet=", "#review", "#details")
        ):
            continue
        text = clean_text(
            listing_node_attr(anchor, "title")
            or listing_node_attr(anchor, "aria-label")
            or listing_node_text(anchor)
        )
        score = _card_title_score(
            text=text,
            attrs=listing_node_signature(anchor),
            tag_name=listing_node_tag(anchor),
            href_present=True,
        )
        if listing_detail_like_path(url, is_job=is_job):
            score += 6
        if any(
            token in lowered_url
            for token in ("/seller/", "/profile/", "/brand/", "/help/", "/search")
        ):
            score -= 5
        if title_index >= 0 and card_html:
            anchor_html = listing_node_html(anchor)
            anchor_index = card_html.find(anchor_html) if anchor_html else -1
            if 0 <= anchor_index < title_index:
                score += 3
            elif anchor_index > title_index:
                score -= 3
        if best is None or score > best[0]:
            best = (score, anchor, url, text)
    if best is None:
        return None
    score, anchor, url, text = best
    return anchor, url, text, score


def _select_primary_card_url(
    card,
    page_url: str,
) -> str:
    selectors = ",".join(f"[{attr}]" for attr in LISTING_CARD_URL_ATTRS)
    candidates = [card, *listing_node_css(card, selectors)]
    for candidate in candidates:
        for attr_name in LISTING_CARD_URL_ATTRS:
            url = absolute_url(page_url, listing_node_attr(candidate, attr_name))
            if url and not listing_url_is_structural(url, page_url):
                return url
    return ""


def _extract_page_images_from_node(root, page_url: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for node in listing_node_css(root, "img"):
        for attr_name in ("data-original", "data-src", "src"):
            candidate = absolute_url(page_url, listing_node_attr(node, attr_name))
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered.startswith("data:"):
                continue
            if _listing_image_candidate_is_noise(node, candidate_url=candidate):
                continue
            if any(
                token in lowered
                for token in (
                    "analytics",
                    "tracking",
                    "pixel",
                    "spacer",
                    "blank.gif",
                    "doubleclick",
                    "google-analytics",
                    "googletagmanager",
                )
            ):
                continue
            if candidate in seen:
                break
            seen.add(candidate)
            values.append(candidate)
            break
    return values[:12]


def _listing_image_candidate_is_noise(node, *, candidate_url: str = "") -> bool:
    context = " ".join(
        part
        for part in (
            str(candidate_url or "").strip().lower(),
            listing_node_signature(node),
            listing_node_attr(node, "alt").lower(),
            listing_node_attr(node, "title").lower(),
            listing_node_attr(node, "aria-label").lower(),
        )
        if part
    )
    return any(
        token in context
        for token in (*NON_PRODUCT_IMAGE_HINTS, *NON_PRODUCT_PROVIDER_HINTS)
    )


def _extract_image_title_hint(root, *, page_url: str) -> str | None:
    for node in listing_node_css(root, "img"):
        candidate_url = absolute_url(
            page_url,
            listing_node_attr(node, "data-original")
            or listing_node_attr(node, "data-src")
            or listing_node_attr(node, "src"),
        )
        if _listing_image_candidate_is_noise(node, candidate_url=candidate_url):
            continue
        for attr_name in ("alt", "title", "aria-label"):
            candidate = _normalize_listing_title(
                clean_text(listing_node_attr(node, attr_name))
            )
            if not candidate or is_title_noise(candidate):
                continue
            return candidate
    return None


def _normalize_listing_title(title: str) -> str:
    normalized = clean_text(title)
    lowered = normalized.lower()
    for prefix in TITLE_PROMOTION_PREFIXES:
        if lowered.startswith(prefix):
            return clean_text(normalized[len(prefix) :])
    return normalized


def _title_token_overlap(left: str, right: str) -> int:
    left_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(left).lower())
        if len(token) >= 3 and token not in {"and", "for", "the", "with"}
    }
    right_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(right).lower())
        if len(token) >= 3 and token not in {"and", "for", "the", "with"}
    }
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens)


def _should_replace_title_with_image_hint(
    title: str, image_title_hint: str | None
) -> bool:
    hint = clean_text(image_title_hint)
    current = clean_text(title)
    if not hint or is_title_noise(hint):
        return False
    if not current:
        return True
    if current == hint:
        return False
    if is_title_noise(current):
        return True
    return _title_token_overlap(current, hint) == 0


def _extract_label_value_pairs_from_node(root) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for tr in listing_node_css(root, "tr"):
        cells = listing_node_css(tr, "th, td")
        if len(cells) < 2:
            continue
        label = listing_node_text(cells[0])
        value = listing_node_text(cells[1])
        if label and value and not _label_value_pair_is_noise(label):
            rows.append((label, value))
    for node in listing_node_css(root, "li, p, div, span"):
        text = listing_node_text(node)
        if ":" not in text:
            continue
        label, value = text.split(":", 1)
        label = clean_text(label)
        value = clean_text(value)
        if not label or not value:
            continue
        if len(label) > 40 or len(value) > 250:
            continue
        if _label_value_pair_is_noise(label):
            continue
        rows.append((label, value))
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for label, value in rows:
        key = (label.lower(), value.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((label, value))
    return deduped


def _label_value_pair_is_noise(label: str) -> bool:
    normalized = clean_text(label).lower()
    if not normalized:
        return True
    if any(token in normalized for token in _LISTING_STRUCTURE_NEGATIVE_HINTS):
        return True
    return any(token in normalized for token in LISTING_LABEL_NOISE_TOKENS)


def _extract_brand_signal_from_card(card, title: str) -> str | None:
    title_text = clean_text(title).casefold()
    for selector in LISTING_BRAND_SELECTORS:
        try:
            matches = listing_node_css(card, str(selector))
        except SelectolaxError:
            continue
        for node in matches:
            value = clean_text(
                listing_node_attr(node, "content")
                or listing_node_attr(node, "title")
                or listing_node_attr(node, "aria-label")
                or listing_node_text(node)
            )
            if not value:
                continue
            if value.casefold() == title_text:
                continue
            if PRICE_RE.search(value):
                continue
            if (
                len(re.findall(r"[a-z0-9]+", value, flags=re.I))
                > LISTING_BRAND_MAX_WORDS
            ):
                continue
            if is_title_noise(value):
                continue
            return value
    return None


title_from_url = _title_from_url
same_url_anchor_text_candidates = _same_url_anchor_text_candidates
extract_price_signal_from_card = _extract_price_signal_from_card
card_title_node = _card_title_node
card_title_score = _card_title_score
select_primary_anchor = _select_primary_anchor
select_primary_card_url = _select_primary_card_url
extract_page_images_from_node = _extract_page_images_from_node
extract_image_title_hint = _extract_image_title_hint
should_replace_title_with_image_hint = _should_replace_title_with_image_hint
normalize_listing_title = _normalize_listing_title
title_token_overlap = _title_token_overlap
extract_label_value_pairs_from_node = _extract_label_value_pairs_from_node
extract_brand_signal_from_card = _extract_brand_signal_from_card
