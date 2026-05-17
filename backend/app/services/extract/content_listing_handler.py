from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.extract.table_extractor import (
    meaningful_listing_table,
    table_headers,
)
from app.services.shared.field_coerce import absolute_url, clean_text, finalize_record

_TABLE_ROW_INTERNAL_FIELDS = frozenset({"_source", "_extraction_mode"})


def validate_table_rows_quality(listing_rows: list[dict[str, Any]]) -> bool:
    meaningful_rows = 0
    for row in listing_rows:
        meaningful_values = [
            clean_text(value)
            for key, value in row.items()
            if key not in _TABLE_ROW_INTERNAL_FIELDS and clean_text(value)
        ]
        if any(len(value) >= 3 for value in meaningful_values):
            meaningful_rows += 1
    return meaningful_rows > 0 and meaningful_rows == len(listing_rows)


def table_row_records(html: str, page_url: str, *, max_records: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    table = _largest_meaningful_table(soup)
    if table is None:
        return []
    headers = table_headers(table)
    row_pairs = _table_row_pairs(table, headers)
    if len(row_pairs) < 3:
        return []
    records: list[dict[str, Any]] = []
    for tr, row in row_pairs:
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


def has_table_row_intent(html: str) -> bool:
    soup = BeautifulSoup(html or "", "html.parser")
    return any(_table_has_row_intent(table) for table in soup.find_all("table"))


def _largest_meaningful_table(soup: BeautifulSoup) -> Tag | None:
    candidates: list[tuple[int, Tag]] = []
    for table in soup.find_all("table"):
        if not meaningful_listing_table(table):
            continue
        headers = table_headers(table)
        row_count = len(_table_row_pairs(table, headers))
        if row_count >= 3:
            candidates.append((row_count * max(1, len(headers)), table))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _table_has_row_intent(table: Tag) -> bool:
    if not meaningful_listing_table(table):
        return False
    rows = table.find_all("tr")
    if len(rows) < 3:
        return False
    return True


def _table_row_pairs(table: Tag, headers: list[str]) -> list[tuple[Tag, dict[str, str]]]:
    pairs: list[tuple[Tag, dict[str, str]]] = []
    if not headers or headers == ["field", "value"]:
        return pairs
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        row: dict[str, str] = {}
        for index, cell in enumerate(cells[: len(headers)]):
            value = clean_text(cell.get_text(" ", strip=True))
            if value:
                row[headers[index]] = value
        if row:
            pairs.append((tr, row))
    return pairs


def _row_url(row: Tag, page_url: str) -> str:
    for link in row.find_all("a", href=True):
        text = clean_text(link.get_text(" ", strip=True))
        href = link.get("href")
        if text and href:
            return absolute_url(page_url, href) or ""
    return ""
