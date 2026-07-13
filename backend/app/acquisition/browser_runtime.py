from __future__ import annotations

import logging

from app.acquisition.browser_capture import (
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.acquisition.browser_screenshot import capture_browser_screenshot
from app.acquisition.browser_diagnostics import (
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
)
from app.acquisition.browser_fetch_runner import (
    browser_fetch,
    browser_storage_state_is_persistable as _browser_storage_state_is_persistable,
)
from app.acquisition.browser_pool import (
    SharedBrowserRuntime,
    browser_runtime_snapshot,
    get_browser_runtime,
    patchright_browser_available,
    real_chrome_browser_available,
    real_chrome_candidate_paths,
    real_chrome_executable_path,
    shutdown_browser_runtime,
    shutdown_browser_runtime_sync,
)
from app.acquisition.browser_proxy_config import display_proxy as _display_proxy
from app.acquisition.browser_readiness import (
    classify_browser_outcome,
    looks_like_low_content_shell,
)
from app.acquisition.browser_route_blocking import (
    block_unneeded_route as _block_unneeded_route,
)
from app.acquisition.runtime import NetworkPayloadReadResult
from app.core.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

block_unneeded_route = _block_unneeded_route
_real_chrome_candidate_paths = real_chrome_candidate_paths

__all__ = [
    "_browser_storage_state_is_persistable",
    "_display_proxy",
    "SharedBrowserRuntime",
    "NetworkPayloadReadResult",
    "browser_fetch",
    "build_browser_diagnostics_contract",
    "browser_runtime_snapshot",
    "block_unneeded_route",
    "build_failed_browser_diagnostics",
    "capture_browser_screenshot",
    "classify_network_endpoint",
    "classify_browser_outcome",
    "crawler_runtime_settings",
    "get_browser_runtime",
    "looks_like_low_content_shell",
    "patchright_browser_available",
    "read_network_payload_body",
    "real_chrome_browser_available",
    "real_chrome_candidate_paths",
    "real_chrome_executable_path",
    "should_capture_network_payload",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
]
