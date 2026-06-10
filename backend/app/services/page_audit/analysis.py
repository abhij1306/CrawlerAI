from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.services.config import page_audit as config

Check = dict[str, Any]


def analyze_page(
    *,
    url: str,
    source_html: str,
    dom_html: str,
    context: str = config.PAGE_AUDIT_CONTEXT_AUTO,
) -> dict[str, Any]:
    source_soup = BeautifulSoup(source_html or "", "html.parser")
    dom_soup = BeautifulSoup(dom_html or "", "html.parser")
    source_checks, source_facts = _source_checks(source_soup, url=url)
    ecommerce = _is_ecommerce_page(source_soup, dom_soup, context=context)
    dom_checks, dom_facts = _dom_checks(
        dom_soup,
        source_soup=source_soup,
        url=url,
        ecommerce=ecommerce,
        source_facts=source_facts,
    )
    diff_checks, diff_facts = _diff_checks(source_soup, dom_soup, url=url)
    all_checks = [*source_checks, *dom_checks, *diff_checks]
    return {
        "url": url,
        "source_checks": source_checks,
        "dom_checks": dom_checks,
        "diff_checks": diff_checks,
        "scores": _scores(all_checks, ecommerce=ecommerce),
        "critical_failures": [
            check
            for check in all_checks
            if check["severity"] == config.SEVERITY_CRITICAL
            and check["applicable"]
            and not check["passed"]
        ],
        "render_summary": {
            "source_html_bytes": len((source_html or "").encode("utf-8")),
            "dom_html_bytes": len((dom_html or "").encode("utf-8")),
            "dom_only_text_count": diff_facts["dom_only_text_count"],
            "dom_only_link_count": diff_facts["dom_only_link_count"],
            "source_lcp_candidate": diff_facts["source_lcp_candidate"],
            "dom_lcp_candidate": diff_facts["dom_lcp_candidate"],
            "frameworks": dom_facts["frameworks"],
            "ecommerce_detected": ecommerce,
        },
    }


def _source_checks(soup: BeautifulSoup, *, url: str) -> tuple[list[Check], dict[str, Any]]:
    title_nodes = soup.find_all("title")
    title = _node_text(title_nodes[0]) if title_nodes else ""
    description = _meta_content(soup, name="description")
    h1_nodes = soup.find_all("h1")
    h1_text = _node_text(h1_nodes[0]) if h1_nodes else ""
    canonical_nodes = soup.select("link[rel~='canonical']")
    canonical = _absolute_url(url, canonical_nodes[0].get("href")) if canonical_nodes else ""
    robots = _meta_content(soup, name="robots").lower()
    viewport = _meta_content(soup, name="viewport").lower()
    lang = str(soup.html.get("lang") or "").strip() if soup.html else ""
    jsonld_values, jsonld_errors = _jsonld_values(soup)
    schema_types = sorted(_schema_types(jsonld_values))
    page_path = urlparse(url).path.strip("/")
    homepage = not page_path
    product_signals = _has_product_signals(soup, schema_types)
    review_signals = bool(
        soup.select("[itemprop='review'], [itemprop='reviewCount'], [class*='review' i]")
    )
    canonical_target = canonical or url
    checks = [
        _check("title_exists", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_SOURCE, bool(title), title, "non-empty"),
        _check("title_length", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, config.TITLE_MIN_CHARS <= len(title) <= config.TITLE_MAX_CHARS, len(title), f"{config.TITLE_MIN_CHARS}-{config.TITLE_MAX_CHARS}"),
        _check("meta_description_exists", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, bool(description), description, "non-empty"),
        _check("meta_description_length", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, config.META_DESCRIPTION_MIN_CHARS <= len(description) <= config.META_DESCRIPTION_MAX_CHARS, len(description), f"{config.META_DESCRIPTION_MIN_CHARS}-{config.META_DESCRIPTION_MAX_CHARS}"),
        _check("h1_count", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_SOURCE, len(h1_nodes) == 1, len(h1_nodes), 1),
        _check("h1_non_empty", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, bool(h1_text), h1_text, "non-empty"),
        _check("canonical_exists", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, bool(canonical), canonical, url),
        _check("canonical_matches_url", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, _same_url(canonical, url), canonical, url),
        _check("lang_attribute", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, bool(re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", lang)), lang, "BCP47 language code"),
        _check("robots_indexable", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_SOURCE, "noindex" not in robots, robots or "not set", "no noindex"),
        _check("viewport_mobile", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, "width=device-width" in viewport.replace(" ", ""), viewport, "width=device-width"),
        _meta_check(soup, "og_title", property_name="og:title"),
        _meta_check(soup, "og_description", property_name="og:description"),
        _meta_check(soup, "og_image", property_name="og:image"),
        _check("og_url", config.CATEGORY_SEO, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, _same_url(_meta_content(soup, property_name="og:url"), canonical_target), _meta_content(soup, property_name="og:url"), canonical_target),
        _meta_check(soup, "twitter_card", name="twitter:card"),
        _meta_check(soup, "twitter_image", name="twitter:image"),
        _check("jsonld_present", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, bool(soup.select("script[type='application/ld+json']")), len(jsonld_values), "at least 1 block"),
        _check("jsonld_parseable", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_HIGH, config.DATA_SOURCE_SOURCE, not jsonld_errors, jsonld_errors, "no parse errors"),
        _check("schema_types_detected", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, bool(schema_types), schema_types, "at least 1 @type"),
        _check("schema_organization_present", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, "organization" in schema_types, schema_types, "Organization", applicable=homepage),
        _check("schema_breadcrumb_present", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, "breadcrumblist" in schema_types, schema_types, "BreadcrumbList", applicable=not homepage),
        _check("schema_product_present", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_CRITICAL, config.DATA_SOURCE_SOURCE, "product" in schema_types, schema_types, "Product", applicable=product_signals),
        _check("schema_review_present", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_MEDIUM, config.DATA_SOURCE_SOURCE, bool({"review", "aggregaterating"} & set(schema_types)), schema_types, "Review or AggregateRating", applicable=review_signals),
    ]
    return checks, {
        "schema_types": schema_types,
        "jsonld_values": jsonld_values,
        "canonical": canonical,
    }


def _dom_checks(
    soup: BeautifulSoup,
    *,
    source_soup: BeautifulSoup,
    url: str,
    ecommerce: bool,
    source_facts: dict[str, Any],
) -> tuple[list[Check], dict[str, Any]]:
    images = list(soup.find_all("img"))
    lcp = _lcp_candidate(soup)
    source_lcp = _lcp_candidate(source_soup)
    lcp_hidden = _is_hidden(lcp)
    lcp_lazy = bool(lcp and lcp.name == "img" and str(lcp.get("loading") or "").lower() == "lazy")
    above_fold_lazy = [
        _element_summary(image)
        for image in images[: config.ABOVE_FOLD_IMAGE_SAMPLE_SIZE]
        if str(image.get("loading") or "").lower() == "lazy"
    ]
    hero_image = soup.select_one("[class*='hero' i] img, [class*='banner' i] img")
    missing_alt = [_element_summary(image) for image in images if image.get("alt") is None]
    missing_dimensions = [
        _element_summary(image)
        for image in images
        if not image.get("width") or not image.get("height")
    ]
    suspicious_origins = sorted(
        {
            urlparse(_absolute_url(url, image.get("src"))).hostname or ""
            for image in images
            if any(
                token in (urlparse(_absolute_url(url, image.get("src"))).hostname or "")
                for token in config.SUSPICIOUS_IMAGE_HOSTS
            )
        }
    )
    oversized_srcsets = [
        _element_summary(image)
        for image in images
        if len([item for item in str(image.get("srcset") or "").split(",") if item.strip()])
        > config.MAX_SRCSET_ENTRIES
    ]
    external_scripts = list(soup.select("script[src]"))
    blocking_scripts = [
        _element_summary(node)
        for node in soup.select("head script[src]:not([async]):not([defer]):not([type='module'])")
    ]
    script_text = " ".join(str(node.get("src") or "") for node in external_scripts).lower()
    analytics_hits = sorted({token for token in config.ANALYTICS_SIGNALS if token in script_text})
    ab_hits = sorted({token for token in config.AB_TEST_SIGNALS if token in script_text})
    chat_hits = sorted({token for token in config.CHAT_SIGNALS if token in script_text})
    frameworks = _frameworks(str(soup))
    forms = list(soup.find_all("form"))
    forms_without_action = [_element_summary(form) for form in forms if not form.get("action")]
    state_changing_forms = [
        form for form in forms if str(form.get("method") or "get").lower() != "get"
    ]
    forms_without_csrf = [
        _element_summary(form)
        for form in state_changing_forms
        if not form.select_one("input[type='hidden'][name*='csrf' i], input[type='hidden'][name*='token' i]")
    ]
    unlabeled_inputs = [
        _element_summary(control)
        for control in soup.select("input:not([type='hidden']), select, textarea")
        if not _has_label(soup, control)
    ]
    password_autocomplete_off = [
        _element_summary(node)
        for node in soup.select("input[type='password'][autocomplete='off' i]")
    ]
    sensitive_get_forms = [
        _element_summary(form)
        for form in forms
        if str(form.get("method") or "get").lower() == "get"
        and form.select_one("input[type='password'], input[type='email']")
    ]
    broken_anchors = _broken_anchor_links(soup)
    insecure_external_links = _insecure_external_blank_links(soup, url=url)
    duplicate_ids = sorted(
        value for value, count in Counter(str(node.get("id")) for node in soup.select("[id]")).items() if count > 1
    )
    canonical_count = len(soup.select("link[rel~='canonical']"))
    internal_nofollow = _internal_nofollow_links(soup, url=url)
    font_preloads = list(soup.select("link[rel~='preload'][as='font']"))
    font_links = list(soup.select("link[href*='fonts.googleapis.com']"))
    font_families = _font_family_count(soup)
    body_stylesheets = [_element_summary(node) for node in soup.select("body link[rel~='stylesheet']")]
    inline_style_bytes = sum(len(node.get_text().encode("utf-8")) for node in soup.find_all("style"))
    base_nodes = list(soup.find_all("base"))
    checks = [
        _check("lcp_candidate_present", config.CATEGORY_PERFORMANCE, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DOM, lcp is not None, _element_summary(lcp), "identifiable candidate"),
        _check("lcp_candidate_visible", config.CATEGORY_PERFORMANCE, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DOM, not lcp_hidden, _element_summary(lcp), "visible", applicable=lcp is not None),
        _check("lcp_candidate_in_source", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, source_lcp is not None, _element_summary(source_lcp), "candidate in source", applicable=lcp is not None),
        _check("lcp_candidate_lazy_loaded", config.CATEGORY_PERFORMANCE, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DOM, not lcp_lazy, _element_summary(lcp), "not loading=lazy", applicable=bool(lcp and lcp.name == "img")),
        _check("above_fold_images_eager", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not above_fold_lazy, above_fold_lazy, "no lazy images in first viewport"),
        _check("hero_image_priority", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, bool(hero_image and str(hero_image.get("fetchpriority") or "").lower() == "high"), _element_summary(hero_image), "fetchpriority=high", applicable=hero_image is not None),
        _check("images_have_alt", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not missing_alt, missing_alt, "alt attribute on every image"),
        _check("images_have_dimensions", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not missing_dimensions, missing_dimensions, "width and height"),
        _check("image_origins_reliable", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not suspicious_origins, suspicious_origins, "site or CDN origins"),
        _check("srcset_size_reasonable", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not oversized_srcsets, oversized_srcsets, f"at most {config.MAX_SRCSET_ENTRIES} entries"),
        _check("external_script_count", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, len(external_scripts) <= config.MAX_EXTERNAL_SCRIPT_COUNT, len(external_scripts), f"at most {config.MAX_EXTERNAL_SCRIPT_COUNT}"),
        _check("render_blocking_scripts", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not blocking_scripts, blocking_scripts, "none"),
        _check("analytics_stack_bounded", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, len(analytics_hits) <= config.MAX_ANALYTICS_STACK_COUNT, analytics_hits, f"at most {config.MAX_ANALYTICS_STACK_COUNT}"),
        _check("gtm_not_redundant", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not ("googletagmanager.com/gtm.js" in analytics_hits and "googletagmanager.com/gtag/js" in analytics_hits), analytics_hits, "one Google loading path"),
        _check("ab_testing_tools_absent", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not ab_hits, ab_hits, "none"),
        _check("chat_widgets_absent", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not chat_hits, chat_hits, "none"),
        _check("framework_detected", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, True, frameworks, "informational"),
        _check("forms_have_action", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not forms_without_action, forms_without_action, "action on each form"),
        _check("forms_have_csrf", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not forms_without_csrf, forms_without_csrf, "CSRF token"),
        _check("inputs_have_labels", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not unlabeled_inputs, unlabeled_inputs, "label or aria-label"),
        _check("password_autocomplete_allowed", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not password_autocomplete_off, password_autocomplete_off, "autocomplete enabled"),
        _check("sensitive_forms_not_get", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not sensitive_get_forms, sensitive_get_forms, "POST"),
        _check("anchor_targets_exist", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not broken_anchors, broken_anchors, "existing target IDs"),
        _check("external_blank_links_secure", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not insecure_external_links, insecure_external_links, "rel=noopener noreferrer"),
        _check("duplicate_ids_absent", config.CATEGORY_ACCESSIBILITY, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not duplicate_ids, duplicate_ids, "unique IDs"),
        _check("single_canonical", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DOM, canonical_count <= 1, canonical_count, "at most 1"),
        _check("internal_nofollow_absent", config.CATEGORY_SEO, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not internal_nofollow, internal_nofollow, "none"),
        _check("critical_fonts_preloaded", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, bool(font_preloads), len(font_preloads), "at least 1", applicable=_uses_custom_fonts(soup)),
        _check("font_preloads_crossorigin", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, all(node.has_attr("crossorigin") for node in font_preloads), [_element_summary(node) for node in font_preloads if not node.has_attr("crossorigin")], "crossorigin on every font preload"),
        _check("google_fonts_nonblocking", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, not font_links, [_element_summary(node) for node in font_links], "no blocking Google Fonts stylesheet"),
        _check("font_family_count", config.CATEGORY_PERFORMANCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, font_families <= config.MAX_FONT_FAMILIES, font_families, f"at most {config.MAX_FONT_FAMILIES}"),
        _check("stylesheets_in_head", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, not body_stylesheets, body_stylesheets, "none in body"),
        _check("inline_style_size", config.CATEGORY_PERFORMANCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, inline_style_bytes <= config.MAX_INLINE_STYLE_BYTES, inline_style_bytes, f"at most {config.MAX_INLINE_STYLE_BYTES} bytes"),
        _check("single_title", config.CATEGORY_SEO, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, len(soup.find_all("title")) <= 1, len(soup.find_all("title")), "at most 1"),
        _check("base_tag_absent", config.CATEGORY_SEO, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, not base_nodes, [_element_summary(node) for node in base_nodes], "none"),
    ]
    if ecommerce:
        checks.extend(_ecommerce_checks(soup, source_facts=source_facts))
    return checks, {"frameworks": frameworks}


def _diff_checks(
    source_soup: BeautifulSoup,
    dom_soup: BeautifulSoup,
    *,
    url: str,
) -> tuple[list[Check], dict[str, Any]]:
    source_text = set(_meaningful_text_blocks(source_soup))
    dom_text = set(_meaningful_text_blocks(dom_soup))
    dom_only_text = sorted(dom_text - source_text)
    source_links = _link_set(source_soup, url=url)
    dom_links = _link_set(dom_soup, url=url)
    dom_only_links = sorted(dom_links - source_links)
    source_h1 = bool(source_soup.find("h1"))
    dom_h1 = bool(dom_soup.find("h1"))
    source_schema = bool(source_soup.select("script[type='application/ld+json']"))
    dom_schema = bool(dom_soup.select("script[type='application/ld+json']"))
    source_lcp = _element_identity(_lcp_candidate(source_soup))
    dom_lcp = _element_identity(_lcp_candidate(dom_soup))
    checks = [
        _check("content_present_in_source", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DIFF, not dom_only_text, dom_only_text[: config.DOM_ONLY_TEXT_SAMPLE_SIZE], "no important DOM-only content"),
        _check("links_present_in_source", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DIFF, not dom_only_links, dom_only_links[: config.DOM_ONLY_LINK_SAMPLE_SIZE], "no DOM-only links"),
        _check("h1_present_in_source", config.CATEGORY_SEO, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DIFF, not dom_h1 or source_h1, {"source": source_h1, "dom": dom_h1}, "H1 in source"),
        _check("schema_present_in_source", config.CATEGORY_STRUCTURED_DATA, config.SEVERITY_HIGH, config.DATA_SOURCE_DIFF, not dom_schema or source_schema, {"source": source_schema, "dom": dom_schema}, "JSON-LD in source"),
        _check("lcp_candidate_matches_source", config.CATEGORY_PERFORMANCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DIFF, not dom_lcp or source_lcp == dom_lcp, {"source": source_lcp, "dom": dom_lcp}, "same candidate"),
    ]
    return checks, {
        "dom_only_text_count": len(dom_only_text),
        "dom_only_link_count": len(dom_only_links),
        "source_lcp_candidate": source_lcp,
        "dom_lcp_candidate": dom_lcp,
    }


def _ecommerce_checks(soup: BeautifulSoup, *, source_facts: dict[str, Any]) -> list[Check]:
    schema_types = set(source_facts["schema_types"])
    product_blocks = [
        item
        for item in source_facts["jsonld_values"]
        if "product" in _schema_types([item])
    ]
    offers = [block.get("offers") for block in product_blocks if isinstance(block, dict)]
    offer_rows = [
        row
        for value in offers
        for row in (value if isinstance(value, list) else [value])
        if isinstance(row, dict)
    ]
    price_present = bool(soup.select(", ".join(config.PRICE_SELECTORS)))
    add_to_cart = bool(soup.select(", ".join(config.ADD_TO_CART_SELECTORS)))
    variants = bool(soup.select(", ".join(config.VARIANT_SELECTORS)))
    stock_signal = bool(soup.select(", ".join(config.OUT_OF_STOCK_SELECTORS))) or any(
        row.get("availability") for row in offer_rows
    )
    breadcrumbs = bool(soup.select(", ".join(config.BREADCRUMB_SELECTORS)))
    review_count = bool(soup.select(", ".join(config.REVIEW_COUNT_SELECTORS)))
    offers_complete = any(row.get("price") and row.get("availability") for row in offer_rows)
    return [
        _check("ecommerce_price_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_CRITICAL, config.DATA_SOURCE_DOM, price_present, price_present, True),
        _check("ecommerce_product_schema_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, "product" in schema_types, sorted(schema_types), "Product"),
        _check("ecommerce_offers_complete", config.CATEGORY_ECOMMERCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, offers_complete, offer_rows, "price and availability"),
        _check("ecommerce_add_to_cart_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_HIGH, config.DATA_SOURCE_DOM, add_to_cart, add_to_cart, True),
        _check("ecommerce_variants_detected", config.CATEGORY_ECOMMERCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, variants, variants, True),
        _check("ecommerce_stock_signal_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, stock_signal, stock_signal, True),
        _check("ecommerce_breadcrumbs_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_MEDIUM, config.DATA_SOURCE_DOM, breadcrumbs, breadcrumbs, True),
        _check("ecommerce_review_count_present", config.CATEGORY_ECOMMERCE, config.SEVERITY_LOW, config.DATA_SOURCE_DOM, review_count, review_count, True),
    ]


def _check(
    check_id: str,
    category: str,
    severity: str,
    data_source: str,
    passed: bool,
    detected_value: object,
    expected_value: object,
    *,
    applicable: bool = True,
) -> Check:
    label, fix = config.CHECK_COPY[check_id]
    return {
        "id": check_id,
        "label": label,
        "category": category,
        "severity": severity,
        "data_source": data_source,
        "passed": bool(passed) if applicable else True,
        "applicable": applicable,
        "detected_value": detected_value,
        "expected_value": expected_value,
        "fix": fix,
    }


def _meta_check(
    soup: BeautifulSoup,
    check_id: str,
    *,
    name: str | None = None,
    property_name: str | None = None,
) -> Check:
    value = _meta_content(soup, name=name, property_name=property_name)
    return _check(
        check_id,
        config.CATEGORY_SEO,
        config.SEVERITY_MEDIUM,
        config.DATA_SOURCE_SOURCE,
        bool(value),
        value,
        "non-empty",
    )


def _scores(checks: list[Check], *, ecommerce: bool) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for category in (
        config.CATEGORY_SEO,
        config.CATEGORY_PERFORMANCE,
        config.CATEGORY_STRUCTURED_DATA,
        config.CATEGORY_ACCESSIBILITY,
        config.CATEGORY_ECOMMERCE,
    ):
        if category == config.CATEGORY_ECOMMERCE and not ecommerce:
            result[category] = None
            continue
        rows = [
            check
            for check in checks
            if check["category"] == category and check["applicable"]
        ]
        total = sum(config.SEVERITY_WEIGHTS[str(check["severity"])] for check in rows)
        passed = sum(
            config.SEVERITY_WEIGHTS[str(check["severity"])]
            for check in rows
            if check["passed"]
        )
        result[category] = round((passed / total) * 100, 1) if total else 100.0
    return result


def _meta_content(
    soup: BeautifulSoup,
    *,
    name: str | None = None,
    property_name: str | None = None,
) -> str:
    selector = f"meta[name='{name}']" if name else f"meta[property='{property_name}']"
    node = soup.select_one(selector)
    return str(node.get("content") or "").strip() if node else ""


def _jsonld_values(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], list[str]]:
    values: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, node in enumerate(soup.select("script[type='application/ld+json']")):
        raw = node.string or node.get_text()
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            errors.append(f"script[{index}]: {exc}")
            continue
        for item in parsed if isinstance(parsed, list) else [parsed]:
            if isinstance(item, dict):
                values.append(item)
    return values, errors


def _schema_types(values: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            raw_type = value.get("@type")
            for item in raw_type if isinstance(raw_type, list) else [raw_type]:
                text = str(item or "").strip().rsplit("/", 1)[-1].lower()
                if text:
                    found.add(text)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(values)
    return found


def _has_product_signals(soup: BeautifulSoup, schema_types: list[str]) -> bool:
    return "product" in schema_types or bool(
        soup.select(", ".join((*config.PRICE_SELECTORS, *config.ADD_TO_CART_SELECTORS)))
    )


def _is_ecommerce_page(
    source_soup: BeautifulSoup,
    dom_soup: BeautifulSoup,
    *,
    context: str,
) -> bool:
    if context == config.PAGE_AUDIT_CONTEXT_ECOMMERCE:
        return True
    if context == config.PAGE_AUDIT_CONTEXT_GENERIC:
        return False
    values, _ = _jsonld_values(source_soup)
    return _has_product_signals(dom_soup, sorted(_schema_types(values)))


def _lcp_candidate(soup: BeautifulSoup) -> Tag | None:
    for selector in config.LCP_CANDIDATE_SELECTORS:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


def _is_hidden(node: Tag | None) -> bool:
    current = node
    while isinstance(current, Tag):
        style = str(current.get("style") or "").replace(" ", "").lower()
        if current.has_attr("hidden") or current.get("aria-hidden") == "true":
            return True
        if "display:none" in style or "visibility:hidden" in style:
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def _has_label(soup: BeautifulSoup, node: Tag) -> bool:
    if node.get("aria-label") or node.get("aria-labelledby"):
        return True
    node_id = str(node.get("id") or "").strip()
    if node_id and soup.find("label", attrs={"for": node_id}):
        return True
    return node.find_parent("label") is not None


def _broken_anchor_links(soup: BeautifulSoup) -> list[str]:
    existing = {str(node.get("id")) for node in soup.select("[id]")}
    return sorted(
        {
            str(node.get("href"))
            for node in soup.select("a[href^='#']")
            if str(node.get("href") or "") not in {"", "#"}
            and str(node.get("href"))[1:] not in existing
        }
    )


def _insecure_external_blank_links(soup: BeautifulSoup, *, url: str) -> list[str]:
    host = urlparse(url).hostname
    failures: list[str] = []
    for node in soup.select("a[target='_blank'][href]"):
        href = _absolute_url(url, node.get("href"))
        if urlparse(href).hostname == host:
            continue
        rel = {str(value).lower() for value in (node.get("rel") or [])}
        if not {"noopener", "noreferrer"}.issubset(rel):
            failures.append(href)
    return sorted(set(failures))


def _internal_nofollow_links(soup: BeautifulSoup, *, url: str) -> list[str]:
    host = urlparse(url).hostname
    return sorted(
        {
            _absolute_url(url, node.get("href"))
            for node in soup.select("a[rel~='nofollow'][href]")
            if urlparse(_absolute_url(url, node.get("href"))).hostname == host
        }
    )


def _font_family_count(soup: BeautifulSoup) -> int:
    values: set[str] = set()
    for node in soup.find_all("style"):
        for match in re.findall(r"font-family\s*:\s*([^;}]+)", node.get_text(), re.I):
            family = match.split(",", 1)[0].strip(" '\"").lower()
            if family:
                values.add(family)
    for node in soup.select("link[href*='fonts.googleapis.com']"):
        query = str(node.get("href") or "")
        values.update(
            match.replace("+", " ").lower()
            for match in re.findall(r"family=([^:&]+)", query)
        )
    return len(values)


def _uses_custom_fonts(soup: BeautifulSoup) -> bool:
    return bool(soup.select("link[href*='font'], style")) and _font_family_count(soup) > 0


def _frameworks(html: str) -> list[str]:
    lowered = html.lower()
    return sorted(
        name
        for name, signals in config.FRAMEWORK_SIGNALS.items()
        if any(signal.lower() in lowered for signal in signals)
    )


def _meaningful_text_blocks(soup: BeautifulSoup) -> list[str]:
    blocks: list[str] = []
    for node in soup.select("h1, h2, h3, h4, h5, h6, p, li, td, th"):
        text = _node_text(node)
        if len(text) >= 20:
            blocks.append(text)
    return list(dict.fromkeys(blocks))


def _link_set(soup: BeautifulSoup, *, url: str) -> set[str]:
    return {
        _absolute_url(url, node.get("href")).split("#", 1)[0]
        for node in soup.select("a[href]")
        if str(node.get("href") or "").strip()
        and not str(node.get("href") or "").startswith(("javascript:", "mailto:", "tel:", "#"))
    }


def _element_summary(node: Tag | None) -> str:
    if not isinstance(node, Tag):
        return ""
    identity = str(node.get("id") or "").strip()
    classes = ".".join(str(value) for value in (node.get("class") or [])[:3])
    source = str(node.get("src") or node.get("href") or "").strip()
    suffix = f"#{identity}" if identity else (f".{classes}" if classes else "")
    return f"{node.name}{suffix}{f' {source}' if source else ''}".strip()


def _element_identity(node: Tag | None) -> str:
    if not isinstance(node, Tag):
        return ""
    return "|".join(
        (
            node.name,
            str(node.get("id") or ""),
            ".".join(str(value) for value in (node.get("class") or [])),
            str(node.get("src") or node.get("poster") or ""),
            _node_text(node)[:120],
        )
    )


def _node_text(node: Tag | None) -> str:
    return " ".join(str(node.get_text(" ", strip=True) if node else "").split())


def _absolute_url(base_url: str, value: object) -> str:
    return urljoin(base_url, str(value or "").strip())


def _same_url(left: str, right: str) -> bool:
    def normalized(value: str) -> tuple[str, str, str]:
        parsed = urlparse(value)
        return (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.path.rstrip("/") or "/",
        )

    return bool(left and right and normalized(left) == normalized(right))
