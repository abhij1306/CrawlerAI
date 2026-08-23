from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit
from typing import Any, cast

from app.acquisition.platform_policy import (
    configured_adapter_names,
    platform_config_for_family,
)
from app.persistence.publish import VERDICT_PARTIAL, VERDICT_SUCCESS
from app.persistence.publish.metrics import diagnostics_indicate_block

_UTILITY_RECORD_TOKENS = frozenset(
    {
        "cart",
        "checkout",
        "contact",
        "faq",
        "help",
        "login",
        "privacy",
        "returns",
        "search",
        "shipping",
        "sign in",
        "wishlist",
    }
)
_SUCCESS_VERDICTS = {VERDICT_SUCCESS.lower(), VERDICT_PARTIAL.lower()}
_PLACEHOLDER_TITLES = {"404", "all products", "edit", "page not found", "sylius demo"}
_IDENTITY_SEGMENT_SKIP = {
    "c",
    "catalog",
    "collections",
    "dp",
    "item",
    "items",
    "p",
    "page",
    "product",
    "products",
    "release",
    "releases",
    "shop",
    "store",
    "w",
}
_IDENTITY_TOKEN_SKIP = {"and", "for", "from", "the", "with"}
_GENERIC_DETAIL_SECTION_TITLES = {
    "customers also bought",
    "frequently bought together",
    "recommended products",
    "related products",
    "you may also like",
}


def _safe_int(value: object) -> int:
    try:
        return int(cast(Any, value) or 0)
    except (TypeError, ValueError):
        return 0


def _object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = ["classify_failure_mode"]


def unavailable_configured_adapters() -> set[str]:
    # The legacy adapter registry was a no-op and has been retired. Configured
    # names remain diagnostic expectations until concrete connectors exist.
    return set(configured_adapter_names())


def classify_failure_mode(
    result: dict[str, object], *, missing_registrations: set[str] | None = None
) -> str:
    verdict = str(result.get("verdict") or "").strip().lower()
    diagnostics = _object_dict(result.get("browser_diagnostics"))
    error_text = str(result.get("error") or "").lower()
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    failure_kind = str(diagnostics.get("failure_kind") or "").strip().lower()
    status_code = _safe_int(result.get("status_code"))
    primary = _primary_failure_mode(
        result,
        verdict=verdict,
        diagnostics=diagnostics,
        error_text=error_text,
        browser_outcome=browser_outcome,
        failure_kind=failure_kind,
        status_code=status_code,
    )
    if primary is not None:
        return primary
    return _adapter_failure_mode(result, missing_registrations=missing_registrations)


def _primary_failure_mode(
    result: dict[str, object],
    *,
    verdict: str,
    diagnostics: dict[str, object],
    error_text: str,
    browser_outcome: str,
    failure_kind: str,
    status_code: int,
) -> str | None:
    success = verdict in _SUCCESS_VERDICTS
    if success and _looks_like_detail_identity_mismatch(result):
        return "detail_identity_mismatch"
    if success and not _looks_like_placeholder_or_wrong_content(result, diagnostics):
        return "success"
    fixed_signals = (
        (bool(diagnostics.get("networkidle_timed_out")), "spa_readiness_timeout"),
        (
            browser_outcome == "low_content_shell" and status_code in {404, 410},
            "spa_shell_404",
        ),
        (browser_outcome == "low_content_shell", "spa_shell_low_content"),
        (failure_kind in {"unsupported_proxy", "proxy_error"}, "proxy_failure"),
        (failure_kind == "engine_unavailable", "engine_failure"),
        ("timeout" in error_text, "timeout"),
        ("getaddrinfo failed" in error_text, "dns_or_network_failure"),
        ("chrome-error://chromewebdata/" in error_text, "browser_navigation_failure"),
        (verdict == "blocked", "blocked"),
        (_result_indicates_challenge(result, diagnostics), "blocked"),
        (verdict == "listing_detection_failed", "listing_extraction_empty"),
        (verdict == "empty", "detail_extraction_empty"),
        (verdict == "error", "error"),
        (
            _looks_like_placeholder_or_wrong_content(result, diagnostics),
            "wrong_content_or_placeholder",
        ),
    )
    return next((mode for matched, mode in fixed_signals if matched), None)


def _result_indicates_challenge(
    result: dict[str, object], diagnostics: dict[str, object]
) -> bool:
    return (
        bool(result.get("blocked"))
        or _diagnostics_indicate_challenge(diagnostics)
        or _diagnostics_contain_strong_challenge_evidence(diagnostics)
    )


def _adapter_failure_mode(
    result: dict[str, object], *, missing_registrations: set[str] | None
) -> str:
    family = str(result.get("platform_family") or "").strip().lower()
    platform_config = platform_config_for_family(family) if family else None
    expected_adapters = _expected_adapter_names(platform_config)
    if missing_registrations is None:
        missing_registrations = unavailable_configured_adapters()
    if expected_adapters and expected_adapters.issubset(missing_registrations):
        return "adapter_not_registered"
    if expected_adapters and not result.get("adapter_name"):
        return "adapter_not_matched"
    if (
        family
        and not expected_adapters
        and str(result.get("surface") or "").startswith("job_")
    ):
        return "platform_family_without_adapter"
    if _safe_int(result.get("records")) == 0:
        return (
            "listing_extraction_empty"
            if str(result.get("surface") or "").endswith("_listing")
            else "detail_extraction_empty"
        )
    return "unknown_failure"


def _expected_adapter_names(platform_config: object) -> set[str]:
    names = getattr(platform_config, "adapter_names", ())
    return {str(name).strip().lower() for name in names if str(name or "").strip()}


def _diagnostics_indicate_challenge(diagnostics: dict[str, object]) -> bool:
    return diagnostics_indicate_block(diagnostics)


def _diagnostics_contain_strong_challenge_evidence(
    diagnostics: dict[str, object],
) -> bool:
    evidence = [
        str(item or "").strip().lower()
        for item in _object_list(diagnostics.get("challenge_evidence"))
        if str(item or "").strip()
    ]
    if any(
        item.startswith(("strong:", "title:", "active_provider:", "challenge_element:"))
        for item in evidence
    ):
        return True
    return bool(diagnostics.get("challenge_element_hits")) and bool(
        diagnostics.get("challenge_provider_hits")
    )


def _challenge_summary_from_diagnostics(
    diagnostics: dict[str, object],
) -> dict[str, object] | None:
    if not _diagnostics_indicate_challenge(diagnostics):
        return None
    provider_hits = _nonempty_strings(diagnostics.get("challenge_provider_hits"))
    element_hits = _nonempty_strings(diagnostics.get("challenge_element_hits"))
    evidence = _nonempty_strings(diagnostics.get("challenge_evidence"))
    summary: dict[str, object] = {
        "browser_outcome": str(diagnostics.get("browser_outcome") or "").strip().lower()
        or None,
        "provider": provider_hits[0].lower() if provider_hits else None,
        "providers": [item.lower() for item in provider_hits],
        "elements": element_hits,
        "evidence": evidence[:5],
    }
    return summary


def _nonempty_strings(value: object) -> list[str]:
    return [
        str(item or "").strip()
        for item in _object_list(value)
        if str(item or "").strip()
    ]


def _looks_like_placeholder_or_wrong_content(
    result: dict[str, object], diagnostics: dict[str, object]
) -> bool:
    sample_title = str(result.get("sample_title") or "").strip()
    return (
        str(diagnostics.get("browser_outcome") or "").strip().lower()
        == "low_content_shell"
        or (
            _safe_int(result.get("records")) > 0
            and not sample_title
            and _safe_int(result.get("populated_fields")) <= 1
        )
        or _looks_like_placeholder_title(
            sample_title, populated_fields=_safe_int(result.get("populated_fields"))
        )
    )


def _looks_like_utility_chrome_success(result: dict[str, object]) -> bool:
    sample_records = result.get("sample_records")
    if isinstance(sample_records, list):
        for row in sample_records[:2]:
            if not isinstance(row, dict):
                continue
            if _looks_like_utility_record(
                title=row.get("title"),
                url=row.get("url"),
            ):
                return True
    if bool(result.get("sample_looks_like_utility_chrome")):
        return True
    return _looks_like_utility_record(
        title=result.get("sample_title"),
        url=result.get("sample_url"),
    )


def _looks_like_detail_identity_mismatch(result: dict[str, object]) -> bool:
    surface = str(result.get("surface") or "").strip().lower()
    if not surface.endswith("_detail"):
        return False
    requested_url = str(result.get("requested_url") or "").strip()
    if not requested_url:
        return False
    sample_url = str(result.get("sample_url") or "").strip()
    if not sample_url:
        return False
    sample_path = _identity_path(sample_url)
    requested_path = _identity_path(requested_url)
    if sample_path in {"", "/"} and requested_path not in {"", "/"}:
        return True
    requested_tokens = _primary_identity_tokens(requested_url)
    if len(requested_tokens) < 2:
        return False
    sample_url_tokens = _primary_identity_tokens(sample_url)
    sample_title = " ".join(
        str(result.get("sample_title") or "").strip().lower().split()
    )
    sample_title_tokens = _identity_tokens(sample_title)
    overlap = max(
        _identity_overlap_count(requested_tokens, sample_url_tokens),
        _identity_overlap_count(requested_tokens, sample_title_tokens),
    )
    required_overlap = _required_identity_overlap(len(requested_tokens))
    if sample_title in _GENERIC_DETAIL_SECTION_TITLES and overlap < required_overlap:
        return True
    return bool(
        (sample_url_tokens or sample_title_tokens) and overlap < required_overlap
    )


def _looks_like_placeholder_title(title: str, *, populated_fields: int) -> bool:
    normalized = " ".join(str(title or "").strip().lower().split())
    if "can't be found" in normalized or normalized.startswith("oops!"):
        return populated_fields <= 6
    if normalized not in _PLACEHOLDER_TITLES:
        return False
    return populated_fields <= 2


def _looks_like_utility_record(*, title: object, url: object) -> bool:
    return looks_like_utility_record(title=str(title or ""), url=str(url or ""))


def looks_like_utility_record(*, title: str, url: str) -> bool:
    text = f"{title} {url}".casefold()
    return any(token in text for token in _UTILITY_RECORD_TOKENS)


def _identity_path(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    path = str(parsed.path or "").strip()
    if path in {"", "/"} and str(parsed.fragment or "").strip():
        fragment = str(parsed.fragment or "").strip()
        return fragment if fragment.startswith("/") else f"/{fragment}"
    return path


def _looks_like_promo_or_wrong_page(result: dict[str, object]) -> bool:
    sample_title = " ".join(
        str(result.get("sample_title") or "").strip().lower().split()
    )
    sample_url = str(result.get("sample_url") or "").strip().lower()
    promo_tokens = (
        "promo",
        "new arrivals",
        "sale",
        "shop all",
        "category",
        "categories",
    )
    return any(token in sample_title for token in promo_tokens) or any(
        token in sample_url
        for token in ("/promo", "promo-", "products=newarrival", "/sale", "/category")
    )


def _primary_identity_tokens(value: str) -> set[str]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return set()
    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc or raw_value.startswith("/"):
        path = unquote(str(parsed.path or "").strip())
        segments = [segment for segment in path.split("/") if segment]
        for segment in reversed(segments):
            cleaned = re.sub(r"\.html?$", "", segment.strip().lower())
            if not cleaned or cleaned.isdigit() or cleaned in _IDENTITY_SEGMENT_SKIP:
                continue
            return _identity_tokens(cleaned)
        return set()
    return _identity_tokens(unquote(raw_value.lower()))


def _identity_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").strip().lower())
        if len(token) >= 2 and not token.isdigit() and token not in _IDENTITY_TOKEN_SKIP
    }


def _identity_overlap_count(left: set[str], right: set[str]) -> int:
    if not left or not right:
        return 0
    return len(left & right)


def _required_identity_overlap(token_count: int) -> int:
    if token_count <= 2:
        return token_count
    if token_count == 3:
        return 2
    return max(2, (token_count * 3 + 4) // 5)
