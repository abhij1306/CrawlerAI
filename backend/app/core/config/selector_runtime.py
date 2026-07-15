from __future__ import annotations

# Maximum page-text length (characters) for which the selector runtime treats a
# primary iframe as the page body worth extracting from. Consumed by
# ``app.core.records.selectors_runtime``.
SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT = 400

__all__ = [
    "SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT",
]
