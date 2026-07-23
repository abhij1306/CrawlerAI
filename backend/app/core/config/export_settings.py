from __future__ import annotations

import re

MAX_RECORD_PAGE_SIZE = 1000
# Spreadsheet formula-injection guard: cells whose first character can be read
# as a formula/dynamic-reference marker (=, +, -, @, tab, CR) get a single-quote
# prefix at CSV write time (see app/core/shared/csv_safety.py).
CSV_FORMULA_PREFIX_PATTERN = re.compile(r"^[=+\-@\t\r]")
EXPORT_PAGING_HEADER = "X-Export-Paging"
EXPORT_TOTAL_HEADER = "X-Export-Total"
EXPORT_PARTIAL_HEADER = "X-Export-Partial"
EXPORT_QUALITY_GATE_HEADER = "X-Export-Quality-Gate"
EXPORT_QUALITY_REPORT_HEADER = "X-Export-Quality-Report"
EXPORT_REQUIRED_FIELD_MIN_FILL_RATE = 0.8
