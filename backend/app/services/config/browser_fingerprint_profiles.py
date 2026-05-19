from __future__ import annotations

HOST_OS_UA_TOKENS: dict[str, str] = {
    "windows": "windows nt",
    "macos": "macintosh",
    "linux": "linux",
}

HOST_OS_PLATFORM_LABELS: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}

USER_AGENT_PLATFORM_LABELS: tuple[tuple[str, str], ...] = (
    ("windows nt", "Windows"),
    ("macintosh", "macOS"),
    ("mac os x", "macOS"),
    ("linux", "Linux"),
)

NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL: dict[str, str] = {
    "Windows": "Win32",
    "macOS": "MacIntel",
    "Linux": "Linux x86_64",
}
PLATFORM_VERSION_BY_LABEL: dict[str, str] = {
    "Windows": "15.0.0",
    "macOS": "14.0.0",
    "Linux": "6.0.0",
}
CHROME_CLIENT_HINT_BRANDS: tuple[str, ...] = (
    "Not:A-Brand",
    "Google Chrome",
    "Chromium",
)
CHROME_CLIENT_HINT_GREASE_BRAND: str = "Not:A-Brand"
CHROME_CLIENT_HINT_GREASE_VERSION: str = "99"
CHROME_CLIENT_HINT_GREASE_FULL_VERSION: str = "99.0.0.0"
CHROME_RUNTIME_VERSION_FALLBACK: str = "145.0.0.0"

TIMEZONE_ALIASES: dict[str, str] = {
    "asia/calcutta": "Asia/Kolkata",
}

DEVICE_MEMORY_BUCKETS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)

NATIVE_REAL_CHROME_CONTEXT_OPTIONS: dict[str, object] = {"no_viewport": True}
REAL_CHROME_IGNORE_DEFAULT_ARGS: tuple[str, ...] = ("--enable-automation",)
WARMUP_ELIGIBLE_BROWSER_REASONS: frozenset[str] = frozenset(
    {
        "host-preference",
        "http-escalation",
        "platform-required",
        "traversal-required",
        "empty-extraction retry",
        "thin-listing retry",
    }
)
RETRY_REASON_BROWSER_LABELS: dict[str, str] = {
    "post_extraction_detail_shell": "detail-shell retry",
    "post_extraction_challenge_shell": "challenge-shell retry",
}
BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS: frozenset[str] = frozenset(
    {
        "challenge-shell retry",
    }
)
WARMUP_VENDOR_BLOCK_PREFIX: str = "vendor-block:"
BROWSER_REQUIRED_REASONS: frozenset[str] = frozenset(
    {
        "host-preference",
        "http-escalation",
        "traversal-required",
        "vendor-block",
    }
)

__all__ = [
    "CHROME_CLIENT_HINT_BRANDS",
    "CHROME_CLIENT_HINT_GREASE_BRAND",
    "CHROME_CLIENT_HINT_GREASE_FULL_VERSION",
    "CHROME_CLIENT_HINT_GREASE_VERSION",
    "CHROME_RUNTIME_VERSION_FALLBACK",
    "DEVICE_MEMORY_BUCKETS",
    "BROWSER_REQUIRED_REASONS",
    "HOST_OS_PLATFORM_LABELS",
    "HOST_OS_UA_TOKENS",
    "NATIVE_REAL_CHROME_CONTEXT_OPTIONS",
    "NAVIGATOR_PLATFORM_BY_PLATFORM_LABEL",
    "REAL_CHROME_IGNORE_DEFAULT_ARGS",
    "RETRY_REASON_BROWSER_LABELS",
    "TIMEZONE_ALIASES",
    "USER_AGENT_PLATFORM_LABELS",
    "WARMUP_ELIGIBLE_BROWSER_REASONS",
    "WARMUP_VENDOR_BLOCK_PREFIX",
]
