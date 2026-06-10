from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.config import aid_score as config
from app.services.ucp_audit.catalog_crawl import CatalogCrawlResult


@dataclass(slots=True)
class EvidencePacket:
    url: str
    jsonld_product_blocks: list[dict[str, Any]]
    og_tags: dict[str, str]
    dom_fields: dict[str, str]
    extracted_record: dict[str, Any]
    robots_allows_perplexitybot: bool
    robots_allows_gptbot: bool
    sitemap_found: bool
    contradictions: list[Any] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contradictions"] = [asdict(item) for item in self.contradictions]
        return payload


def build_evidence_packets(result: CatalogCrawlResult) -> list[EvidencePacket]:
    from app.services.ucp_audit.contradiction import detect_contradictions

    packets: list[EvidencePacket] = []
    for record in result.product_records:
        packet = EvidencePacket(
            url=_text(record.get("source_url")),
            jsonld_product_blocks=_product_blocks(record.get("_jsonld") or []),
            og_tags=_string_dict(record.get("_og_tags") or result.og_tags),
            dom_fields={
                "title": _text(record.get("title") or record.get("name")),
                "price": _text(record.get("_dom_price") or record.get("price")),
                "description": _best_description(record),
                "page_text_excerpt": _page_text_excerpt(record),
                "availability": _text(record.get("availability")),
                "images": _text(record.get("images") or record.get("image_url") or record.get("image")),
            },
            extracted_record=_public_record(record),
            robots_allows_perplexitybot=_agent_allowed(result.robots_directives, "perplexitybot"),
            robots_allows_gptbot=_agent_allowed(result.robots_directives, "gptbot"),
            sitemap_found=bool(result.sitemap_found),
        )
        packet.contradictions = detect_contradictions(packet)
        packets.append(packet)
    return packets


def _product_blocks(rows: object) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and _type_matches(row, "product")]


def _type_matches(block: dict[str, Any], expected: str) -> bool:
    raw = block.get("@type") or block.get("type")
    values = raw if isinstance(raw, list) else [raw]
    return any(str(value or "").strip().lower().endswith(expected) for value in values)


def _agent_allowed(directives: dict[str, list[str]], agent: str) -> bool:
    rules = directives.get(agent, []) + directives.get("*", [])
    return "/" not in [str(rule).strip() for rule in rules]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _text(item) for key, item in value.items() if _text(item)}


def _text(value: object) -> str:
    if value in (None, [], {}):
        return ""
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def _best_description(record: dict[str, Any]) -> str:
    description = _text(record.get("description"))
    if len(description) >= config.AID_DESCRIPTION_MIN_CHARS:
        return description
    excerpt = _page_text_excerpt(record)
    return excerpt or description


def _page_text_excerpt(record: dict[str, Any]) -> str:
    page_text = _text(record.get("_page_text"))
    if not page_text:
        return ""
    title = _text(record.get("title") or record.get("name"))
    if title:
        index = page_text.lower().find(title.lower())
        if index >= 0:
            page_text = page_text[index:]
    return page_text[: config.AID_PAGE_EVIDENCE_EXCERPT_CHARS].strip()


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
