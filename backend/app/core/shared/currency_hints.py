from __future__ import annotations

from app.core.config.locale_format_rules import (
    currency_hint_from_page_url,
    currency_hint_from_page_url_with_scope as _currency_hint_from_page_url,
)

__all__ = ["_currency_hint_from_page_url", "currency_hint_from_page_url"]
