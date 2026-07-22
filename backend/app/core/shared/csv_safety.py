"""CSV cell sanitization against spreadsheet formula injection.

Exported CSVs are opened in spreadsheet applications that interpret a leading
``=``, ``+``, ``-``, ``@``, tab, or carriage return as a formula or dynamic
reference marker (CSV injection / formula injection). Prefixing those cells
with a single quote neutralizes execution while keeping the value readable.
"""
from __future__ import annotations

from app.core.config.export_settings import CSV_FORMULA_PREFIX_PATTERN

__all__ = ["csv_safe_cell", "sanitize_csv_row"]


def csv_safe_cell(value: object) -> object:
    """Prefix dangerous leading characters with a single quote."""
    if isinstance(value, str) and CSV_FORMULA_PREFIX_PATTERN.match(value):
        return f"'{value}"
    return value


def sanitize_csv_row(row: dict[str, object]) -> dict[str, object]:
    """Sanitize every key and string value of a CSV row mapping.

    Keys are sanitized because CSV header fieldnames derive from record keys.
    """
    return {
        str(csv_safe_cell(str(key))): csv_safe_cell(value)
        for key, value in row.items()
    }
