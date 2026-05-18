from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from app.services.acquisition.acquirer import AcquisitionRequest, acquire
from app.services.acquisition.policy import AcquisitionPolicy
from app.services.acquisition_plan import AcquisitionPlan
from app.services.config import ucp_audit as config
from app.services.pipeline.extract_records import extract_records
from app.services.ucp_audit.product_schema import score_product_schema
from app.services.ucp_audit.types import AgentViewDelta


async def build_agent_view_delta(url: str) -> AgentViewDelta:
    structured = await acquire_url(url, mode=config.UCP_HTTP_ONLY_MODE)
    rendered = await acquire_url(url, mode=config.UCP_BROWSER_ONLY_MODE)
    agent = extract_agent_view(str(getattr(structured, "html", "") or ""), url)
    human = extract_main_crawl_human_view(rendered, url)
    agent_keys = set(agent)
    human_keys = set(human)
    return AgentViewDelta(
        url=url,
        agent_extracted=agent,
        human_visible=human,
        missing_in_agent_view=sorted(human_keys - agent_keys),
        agent_only_signals=sorted(agent_keys - human_keys),
        fidelity_score=compute_fidelity_score(agent, human),
    )


async def acquire_url(url: str, *, mode: str):
    request = AcquisitionRequest(
        run_id=0,
        url=url,
        plan=AcquisitionPlan(surface=config.UCP_AUDIT_SURFACE),
        policy=AcquisitionPolicy(fetch_mode=mode),
    )
    return await acquire(request)


# UA override is not supported by acquisition layer yet.
# This compares default HTTP structured evidence with browser-rendered evidence.
def extract_agent_view(html: str, url: str) -> dict[str, Any]:
    score = score_product_schema(url, html)
    product = _richest_product_jsonld(html)
    offer = score.raw_offers[0] if score.raw_offers else {}
    values: dict[str, Any] = {
        "name": _first_text(product.get("name") if product else None),
        "price": _first_text(offer.get("price") if isinstance(offer, dict) else None),
        "currency": _first_text(
            offer.get(config.POLICY_JSONLD_CURRENCY_FIELD)
            if isinstance(offer, dict)
            else None
        ),
        "availability": _availability_label(
            offer.get("availability") if isinstance(offer, dict) else None
        ),
        "brand": _brand_name(product.get("brand") if product else None),
        "description": _first_text(product.get("description") if product else None),
        "sku": _first_text(
            (offer.get("sku") if isinstance(offer, dict) else None)
            or (product.get("sku") if product else None)
        ),
        "gtin": _first_text(
            (offer.get("gtin") if isinstance(offer, dict) else None)
            or (offer.get("gtin13") if isinstance(offer, dict) else None)
            or (product.get("gtin") if product else None)
            or (product.get("gtin13") if product else None)
        ),
        "additionalProperties": score.raw_additional_properties,
    }
    if score.raw_offers:
        values["variant_offer_count"] = len(score.raw_offers)
    return {key: value for key, value in values.items() if value not in (None, "")}


def extract_main_crawl_human_view(acquisition_result: Any, url: str) -> dict[str, Any]:
    final_url = str(getattr(acquisition_result, "final_url", "") or url)
    records = extract_records(
        str(getattr(acquisition_result, "html", "") or ""),
        final_url,
        config.UCP_AUDIT_SURFACE,
        max_records=config.AGENT_DELTA_HUMAN_MAX_RECORDS,
        requested_page_url=url,
        requested_fields=list(config.AGENT_DELTA_HUMAN_REQUESTED_FIELDS),
        adapter_records=list(getattr(acquisition_result, "adapter_records", []) or []),
        network_payloads=list(getattr(acquisition_result, "network_payloads", []) or []),
        artifacts=dict(getattr(acquisition_result, "artifacts", {}) or {}),
        browser_diagnostics=dict(
            getattr(acquisition_result, "browser_diagnostics", {}) or {}
        ),
        content_type=str(getattr(acquisition_result, "content_type", "") or ""),
    )
    record = records[0] if records and isinstance(records[0], dict) else {}
    return _human_view_from_record(record)


def _human_view_from_record(record: dict[str, Any]) -> dict[str, Any]:
    variants = [item for item in record.get("variants") or [] if isinstance(item, dict)]
    values: dict[str, Any] = {
        "name": _first_text(record.get("title") or record.get("name")),
        "price": _first_text(record.get("price")),
        "currency": _first_text(record.get("currency")),
        "availability": _first_text(record.get("availability")),
        "color_options": _variant_axis_values(variants, "color"),
        "size_options": _variant_axis_values(variants, "size"),
    }
    if variants:
        values["variants"] = variants
        values["variant_count"] = len(variants)
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def _variant_axis_values(variants: list[dict[str, Any]], axis: str) -> list[str]:
    values: list[str] = []
    for variant in variants:
        value = _first_text(variant.get(axis))
        if value and value not in values:
            values.append(value)
    return values


def extract_human_view(html: str, _url: str) -> dict[str, Any]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    name = _first_text(soup.h1.get_text(" ", strip=True) if soup.h1 else None)
    scoped_lines = _visible_lines(_product_scope(soup))
    page_lines = _visible_lines(soup)
    price = _first_price_near_name(scoped_lines, name) or _first_price(scoped_lines)
    if not price:
        price = _first_price_near_name(page_lines, name) or _first_price(page_lines)
    sale_messaging = _first_sale_messaging(scoped_lines) or _first_sale_messaging(page_lines)
    values: dict[str, Any] = {
        "name": name,
        "price": price,
        "sale_messaging": sale_messaging,
        "effective_price": _effective_price(price, sale_messaging),
        "color_options": _option_lines_after(
            scoped_lines,
            config.AGENT_DELTA_COLOR_LABEL,
            stop_labels=config.AGENT_DELTA_COLOR_STOP_LABELS,
            max_words=config.AGENT_DELTA_COLOR_OPTION_MAX_WORDS,
        ),
        "size_options": _option_lines_after(
            scoped_lines,
            config.AGENT_DELTA_SIZE_LABEL,
            stop_labels=config.AGENT_DELTA_SIZE_STOP_LABELS,
            max_words=config.AGENT_DELTA_SIZE_OPTION_MAX_WORDS,
        ),
    }
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def compute_fidelity_score(agent: dict[str, Any], human: dict[str, Any]) -> float:
    human_keys = set(human)
    if not human_keys:
        return 1.0
    return round(len(set(agent) & human_keys) / len(human_keys), 4)


def _richest_product_jsonld(html: str) -> dict[str, Any]:
    from app.services.structured_sources import parse_json_ld

    products = [
        item
        for item in parse_json_ld(BeautifulSoup(str(html or ""), "html.parser"))
        if isinstance(item, dict) and _is_product_type(item.get(config.JSON_LD_TYPE_KEY))
    ]
    if not products:
        return {}
    return max(products, key=lambda item: len([value for value in item.values() if value]))


def _is_product_type(value: object) -> bool:
    values = value if isinstance(value, list) else [value]
    return any(str(item or "").strip() in config.JSON_LD_PRODUCT_TYPES for item in values)


def _brand_name(value: object) -> str | None:
    if isinstance(value, dict):
        return _first_text(value.get("name"))
    return _first_text(value)


def _availability_label(value: object) -> str | None:
    text = _first_text(value)
    if not text:
        return None
    return text.rsplit("/", 1)[-1].replace("schema.org", "").strip()


def _first_text(value: object) -> str | None:
    if isinstance(value, list):
        for item in value:
            parsed = _first_text(item)
            if parsed:
                return parsed
        return None
    if value in (None, "", [], {}):
        return None
    return str(value).strip()


def _visible_lines(soup: Any) -> list[str]:
    text = soup.get_text("\n", strip=True)
    return [line.strip() for line in text.splitlines() if line.strip()]


def _product_scope(soup: BeautifulSoup) -> Any:
    heading = soup.h1
    if heading is None:
        return soup
    node = heading.parent
    best = soup
    best_score = -1
    for _ in range(7):
        if node is None or not hasattr(node, "get_text"):
            break
        lines = _visible_lines(node)
        joined = "\n".join(lines).casefold()
        has_price = _first_price(lines) is not None
        has_cart = "add to cart" in joined or "add to bag" in joined
        has_options = "select size" in joined or "\ncolor" in joined or "color:" in joined
        score = int(has_price) * 3 + int(has_cart) * 4 + int(has_options) * 2
        if score > best_score and len(lines) <= 220:
            best = node
            best_score = score
        node = node.parent
    return best


def _first_price(lines: list[str]) -> str | None:
    import re

    for line in lines:
        match = re.search(r"\$?\s*(\d+(?:\.\d{2})?)", line)
        if match and "$" in line:
            return match.group(1)
    return None


def _first_price_near_name(lines: list[str], name: str | None) -> str | None:
    if not name:
        return None
    folded = name.casefold()
    for index, line in enumerate(lines):
        if folded in line.casefold():
            return _first_price(lines[index : index + 70])
    return None


def _first_sale_messaging(lines: list[str]) -> str | None:
    for line in lines:
        lowered = line.lower()
        if "in cart" in lowered and ("off" in lowered or "discount" in lowered):
            return _clean_sale_messaging(line)
    return None


def _clean_sale_messaging(value: str) -> str:
    import re

    match = re.search(r"(\d+(?:\.\d+)?\s*%\s*off\s+in\s+cart)", value, flags=re.I)
    if match:
        return match.group(1).upper()
    return value.strip()


def _effective_price(price: str | None, sale_messaging: str | None) -> str | None:
    import re

    if not price or not sale_messaging:
        return None
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%\s*off", sale_messaging, flags=re.I)
    if not percent:
        return None
    value = float(price) * (1 - (float(percent.group(1)) / 100))
    return f"{value:.2f}"


def _option_lines_after(
    lines: list[str],
    label: str,
    *,
    stop_labels: tuple[str, ...],
    max_words: int,
) -> list[str]:
    result: list[str] = []
    active = False
    for line in lines:
        if not active:
            active = line.strip(":").casefold() == label.casefold()
            continue
        normalized = line.strip()
        if normalized.strip(":").casefold() == label.casefold():
            continue
        if _is_option_stop_line(normalized, stop_labels):
            break
        if _is_noise_option_line(normalized):
            continue
        if _is_plausible_option_line(normalized, max_words=max_words) and normalized not in result:
            result.append(normalized)
    return result[: config.AGENT_DELTA_OPTION_MAX_COUNT]


def _is_noise_option_line(value: str) -> bool:
    normalized = _option_fold(value)
    if "$" in value:
        return True
    return normalized in config.AGENT_DELTA_OPTION_NOISE_LINES


def _is_plausible_option_line(value: str, *, max_words: int) -> bool:
    import re

    if len(value) > config.AGENT_DELTA_OPTION_MAX_CHARS:
        return False
    if any(char in value for char in config.AGENT_DELTA_OPTION_INVALID_CHARS):
        return False
    words = re.findall(r"[A-Za-z0-9]+", value)
    return len(words) <= max_words


def _is_option_stop_line(value: str, stop_labels: tuple[str, ...]) -> bool:
    normalized = _option_fold(value)
    return any(
        normalized == _option_fold(stop) or _option_fold(stop) in normalized
        for stop in stop_labels
    )


def _option_fold(value: str) -> str:
    return value.strip().replace("\u2019", "'").casefold()
