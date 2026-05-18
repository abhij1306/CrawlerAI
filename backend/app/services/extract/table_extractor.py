from __future__ import annotations

__all__ = (
    "extract_tables",
    "table_headers",
    "table_rows",
    "meaningful_table",
    "meaningful_listing_table",
    "key_value_table",
)

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.services.field_policy import normalize_field_key
from app.services.shared.field_coerce import clean_text


def extract_tables(
    soup: BeautifulSoup | Tag | None,
    content_container: Tag | None = None,
    *,
    remove_from_dom: bool = False,
) -> list[dict[str, Any]]:
    """Extract table records, optionally removing extracted tables from the source DOM."""
    if soup is None:
        return []
    root = content_container or soup
    tables: list[dict[str, Any]] = []
    for table in list(root.find_all("table")):
        if key_value_table(table):
            headers = ["field", "value"]
            rows = table_rows(table, headers)
        elif meaningful_table(table):
            headers = table_headers(table)
            rows = table_rows(table, headers)
        else:
            continue
        if not rows:
            continue
        tables.append(
            {
                "context": _table_context(table, root),
                "headers": headers,
                "rows": rows,
            }
        )
        if remove_from_dom:
            table.decompose()
    return tables


def table_headers(table: Tag) -> list[str]:
    if key_value_table(table):
        return ["field", "value"]
    header_row = table.find("tr")
    if header_row is None:
        return []
    cells = header_row.find_all(["th", "td"], recursive=False)
    if not header_row.find_all("th"):
        return []
    headers: list[str] = []
    for index, cell in enumerate(cells):
        label = clean_text(cell.get_text(" ", strip=True))
        headers.append(normalize_field_key(label) or f"column_{index + 1}")
    return headers


def table_rows(table: Tag, headers: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if headers == ["field", "value"] and key_value_table(table):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if len(cells) < 2:
                continue
            label = _dedupe_repeated_text(clean_text(cells[0].get_text(" ", strip=True)))
            value = _dedupe_repeated_text(clean_text(cells[1].get_text(" ", strip=True)))
            if label and value:
                rows.append({"field": label, "value": value})
        return rows
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
            rows.append(row)
    return rows


def meaningful_table(table: Tag) -> bool:
    if table.find(["input", "select", "textarea"]):
        return False
    if not table.find_all("th"):
        return False
    rows = table.find_all("tr")
    if len(rows) < 3:
        return False
    first_cells = rows[0].find_all(["th", "td"], recursive=False)
    if len(first_cells) < 2:
        return False
    all_cells = table.find_all(["td", "th"])
    if not all_cells:
        return False
    link_only = 0
    for cell in all_cells:
        text = clean_text(cell.get_text(" ", strip=True))
        link_text = clean_text(" ".join(node.get_text(" ", strip=True) for node in cell.find_all(["a", "button"])))
        if text and link_text and text == link_text:
            link_only += 1
    if link_only / max(1, len(all_cells)) > 0.5:
        return False
    text_blob = clean_text(table.get_text(" ", strip=True)).lower()
    if re.search(r"\b(?:sun|mon|tue|wed|thu|fri|sat)\b", text_blob) and re.search(r"\b(?:next|prev|today)\b", text_blob):
        return False
    table_class = " ".join(table.get("class", [])).lower()
    table_id = str(table.get("id") or "").lower()
    return not any(token in f"{table_class} {table_id}" for token in ("nav", "menu", "calendar", "layout"))


def meaningful_listing_table(table: Tag) -> bool:
    return meaningful_table(table) and not key_value_table(table)


def key_value_table(table: Tag) -> bool:
    if table.find(["input", "select", "textarea"]):
        return False
    rows = table.find_all("tr")
    if len(rows) < 2:
        return False
    row_shapes = []
    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) != 2:
            continue
        row_shapes.append((cells[0].name, cells[1].name))
    return len(row_shapes) >= 2 and sum(left == "th" for left, _right in row_shapes) >= max(2, len(row_shapes) // 2)


def _dedupe_repeated_text(value: str) -> str:
    words = value.split()
    if len(words) < 2 or len(words) % 2:
        return value
    midpoint = len(words) // 2
    if words[:midpoint] == words[midpoint:]:
        return " ".join(words[:midpoint])
    return value


def _table_context(table: Tag, root: Tag) -> str:
    caption = table.find("caption")
    if caption:
        caption_text = clean_text(caption.get_text(" ", strip=True))
        if caption_text:
            return caption_text
    current = table
    while current is not None and current is not root:
        previous = current.find_previous_sibling()
        while previous is not None:
            if getattr(previous, "name", "") in {"h1", "h2", "h3", "h4"}:
                heading = clean_text(previous.get_text(" ", strip=True))
                if heading:
                    return heading
            previous = previous.find_previous_sibling()
        current = current.parent if isinstance(current.parent, Tag) else None
    aria = clean_text(table.get("aria-label"))
    if aria:
        return aria
    labelled_by = clean_text(table.get("aria-labelledby"))
    if labelled_by:
        labels = []
        for label_id in labelled_by.split():
            labelled = root.find(id=label_id)
            if labelled:
                label_text = clean_text(labelled.get_text(" ", strip=True))
                if label_text:
                    labels.append(label_text)
        if labels:
            return clean_text(" ".join(labels))
    return ""
