from __future__ import annotations

from app.services.acquisition.browser_identity import build_playwright_context_spec
from app.services.acquisition.browser_proxy_bridge import Socks5AuthBridge
from app.services.acquisition.browser_storage_state import persist_context_storage_state
from app.services.config.browser_fingerprint_profiles import REAL_CHROME_IGNORE_DEFAULT_ARGS

__all__ = [
    "build_playwright_context_spec",
    "Socks5AuthBridge",
    "persist_context_storage_state",
    "REAL_CHROME_IGNORE_DEFAULT_ARGS",
]
