from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.extract.table_extractor import (
    meaningful_listing_table,
    table_headers,
    table_rows,
)
from app.services.shared.field_coerce import absolute_url, clean_text, finalize_record


def table_row_records(html: str, page_url: str, *, max_records: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    table = _largest_meaningful_table(soup)
    if table is None:
        return []
    headers = table_headers(table)
    rows = table_rows(table, headers)
    if len(rows) < 3:
        return []
    records: list[dict[str, Any]] = []
    for tr, row in zip(table.find_all("tr")[1:], rows, strict=False):
        record: dict[str, Any] = {
            **row,
            "source_url": page_url,
            "_source": "content_table_rows",
            "_extraction_mode": "table_rows",
        }
        url = _row_url(tr, page_url)
        if url:
            record["url"] = url
        records.append(finalize_record(record, surface="content_listing"))
        if len(records) >= max_records:
            break
    return records


def _largest_meaningful_table(soup: BeautifulSoup) -> Tag | None:
    candidates: list[tuple[int, Tag]] = []
    for table in soup.find_all("table"):
        if not meaningful_listing_table(table):
            continue
        headers = table_headers(table)
        rows = table_rows(table, headers)
        if len(rows) >= 3:
            candidates.append((len(rows) * max(1, len(headers)), table))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _row_url(row: Tag, page_url: str) -> str:
    for link in row.find_all("a", href=True):
        text = clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        if text and href:
            return absolute_url(page_url, href) or ""
    return ""
