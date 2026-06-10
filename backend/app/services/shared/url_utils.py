from __future__ import annotations

import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

from app.services.config.extraction_rules import (
    BARE_HOST_URL_RE,
    GIF_BASE64_PREFIX,
    PLACEHOLDER_IMAGE_URL_PATTERNS,
    UNRESOLVED_TEMPLATE_URL_TOKENS,
    URL_DETECTION_TOKENS,
)
from app.services.field_url_normalization import is_concatenated_url
from app.services.shared.text_coerce import clean_text

__all__ = [
    "absolute_url",
    "clean_color_tokens",
    "extract_urls",
    "identity_token",
    "same_host",
    "suffix_after_prefix",
    "terminal_text",
    "terminal_tokens",
    "title_preserving_acronyms",
    "title_tokens",
    "variant_url_with_param",
    "ensure_scheme",
    "is_placeholder_image_url",
    "_ensure_scheme",
    "_is_placeholder_image_url",
]

_BARE_HOST_URL_RE = BARE_HOST_URL_RE
gif_base64_prefix = str(GIF_BASE64_PREFIX or "")
url_detection_tokens = tuple(URL_DETECTION_TOKENS or ())
unresolved_template_url_tokens_lower: tuple[str, ...] = tuple(
    str(token).strip().lower()
    for token in tuple(UNRESOLVED_TEMPLATE_URL_TOKENS or ())
    if str(token).strip()
)
placeholder_image_url_tokens = tuple(
    token.lower()
    for token in tuple(PLACEHOLDER_IMAGE_URL_PATTERNS or ())
    if str(token).strip()
)


def absolute_url(base_url: str, candidate: object) -> str:
    text = _clean_url_text(candidate)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme:
        return text
    if text.startswith(("//", "/", "#", "?", "./", "../")):
        return urljoin(base_url, text)
    if _BARE_HOST_URL_RE.fullmatch(text):
        return f"https://{text}"
    origin_relative = _origin_relative_url(base_url, text)
    if origin_relative:
        return origin_relative
    return urljoin(base_url, text)


def variant_url_with_param(page_url: str, variant_id: str) -> str:
    parsed = urlparse(str(page_url or "").strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "variant"
    ]
    query.append(("variant", variant_id))
    composed = urlunparse(parsed._replace(query=urlencode(query)))
    return (
        composed
        if parsed.scheme and parsed.netloc
        else absolute_url(str(page_url or ""), composed) or ""
    )


def _origin_relative_url(base_url: str, candidate: str) -> str:
    parsed_base = urlparse(base_url)
    if not parsed_base.scheme or not parsed_base.netloc:
        return ""
    base_segments = [segment for segment in parsed_base.path.split("/") if segment]
    candidate_segments = [segment for segment in candidate.split("/") if segment]
    if (
        not base_segments
        or len(candidate_segments) < 2
        or base_segments[0] != candidate_segments[0]
        or not _looks_like_locale_segment(candidate_segments[0])
    ):
        return ""
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}/"
    return urljoin(origin, candidate)


def _looks_like_locale_segment(value: str) -> bool:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) == 2 and cleaned.isalpha():
        return True
    if len(cleaned) == 5 and cleaned[2] == "-":
        return cleaned[:2].isalpha() and cleaned[3:].isalpha()
    return False


def _clean_url_text(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    ampersand_marker = "\0AMPERSAND\0"
    protected = re.sub(r"&(amp|#38|#x26);", ampersand_marker, raw, flags=re.I)
    protected = protected.replace("&", ampersand_marker)
    return clean_text(protected).replace(ampersand_marker, "&")


def same_host(base_url: str, candidate_url: str) -> bool:
    base_host = (urlparse(base_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    return bool(candidate_host) and candidate_host == base_host


def terminal_text(value: object) -> str:
    text = _clean_url_text(value)
    if not text:
        return ""
    parsed = urlparse(text)
    parts = [part for part in str(parsed.path or "").split("/") if part]
    if not parts:
        return ""
    return clean_text(unquote(parts[-1]).replace("-", " ").replace("_", " "))


def terminal_tokens(value: object) -> list[str]:
    text = _clean_url_text(value)
    if not text:
        return []
    terminal = unquote(urlparse(text).path.rstrip("/").rsplit("/", 1)[-1])
    return title_tokens(terminal)


def title_tokens(value: object) -> list[str]:
    return [
        identity_token(token)
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if token and token != "s"  # nosec B105
    ]


def suffix_after_prefix(tokens: list[str], prefix: list[str]) -> list[str]:
    if not prefix or len(tokens) <= len(prefix):
        return []
    if tokens[: len(prefix)] == prefix:
        return tokens[len(prefix) :]
    for index, (left, right) in enumerate(zip(tokens, prefix, strict=False)):
        if left != right:
            return tokens[index:]
    return tokens[len(prefix) :]


def clean_color_tokens(tokens: list[str]) -> list[str]:
    cleaned = [
        token for token in tokens if not token.isdigit() and token not in {"html"}
    ]
    while cleaned and cleaned[0] in {"in", "color", "colour"}:
        cleaned = cleaned[1:]
    return cleaned


def identity_token(value: str) -> str:
    if value in {"mens", "womens", "kids"}:
        return value[:-1]
    if len(value) > 4 and value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def title_preserving_acronyms(value: str) -> str:
    return " ".join(
        token.upper() if token.isupper() else token.capitalize()
        for token in clean_text(value).split()
    )


def extract_urls(value: object, page_url: str) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        text = str(value or "").strip()
        if not text:
            return results
        if _looks_like_malformed_relative_url_candidate(text):
            return results
        if is_concatenated_url(text):
            return results
        embedded_urls = re.findall(r"https?://(?:(?!https?://)[^\s,])+", text)
        if len(embedded_urls) >= 2:
            for candidate in embedded_urls:
                absolute = absolute_url(
                    page_url,
                    _trim_trailing_url_candidate(candidate),
                )
                if absolute:
                    results.append(absolute)
        else:
            absolute = absolute_url(page_url, _trim_trailing_url_candidate(text))
            if absolute:
                results.append(absolute)
    elif isinstance(value, dict):
        for key in ("url", "href", "src", "contentUrl", "image", "thumbnail"):
            candidate = value.get(key)
            if candidate in (None, "", [], {}):
                continue
            results.extend(extract_urls(candidate, page_url))
    elif isinstance(value, list):
        for item in value:
            results.extend(extract_urls(item, page_url))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in results:
        normalized = candidate.lower()
        if not candidate or normalized in seen:
            continue
        if _is_placeholder_image_url(candidate) or _is_template_url(candidate):
            continue
        if is_concatenated_url(candidate):
            continue
        seen.add(normalized)
        deduped.append(candidate)
    return deduped


def _ensure_scheme(url: str) -> str:
    stripped = str(url or "").strip()
    if not stripped:
        return stripped
    parsed = urlparse(stripped)
    if parsed.scheme:
        return stripped
    if stripped.startswith(("/", "#", "javascript:")):
        return stripped
    return f"https://{stripped}"


def _is_placeholder_image_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    return any(token in lowered for token in placeholder_image_url_tokens)


def _trim_trailing_url_candidate(value: str) -> str:
    trimmed = str(value or "").rstrip(".,:;!?}'\"")
    while trimmed.endswith((")", "]")):
        closer = trimmed[-1]
        opener = "(" if closer == ")" else "["
        if trimmed.count(closer) <= trimmed.count(opener):
            break
        trimmed = trimmed[:-1].rstrip(".,:;!?}'\"")
    return trimmed


def _looks_like_malformed_relative_url_candidate(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if urlparse(text).scheme or text.startswith(("//", "/", "#", "?", "./", "../")):
        return False
    head = text.split("/", 1)[0].lower()
    if gif_base64_prefix and head.startswith(gif_base64_prefix):
        return True
    return any(token in head for token in url_detection_tokens)


def _is_template_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(token in lowered for token in unresolved_template_url_tokens_lower)


ensure_scheme = _ensure_scheme
is_placeholder_image_url = _is_placeholder_image_url
