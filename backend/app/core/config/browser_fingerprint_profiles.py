from __future__ import annotations

NATIVE_REAL_CHROME_CONTEXT_OPTIONS: dict[str, object] = {"no_viewport": True}
REAL_CHROME_IGNORE_DEFAULT_ARGS: tuple[str, ...] = ("--enable-automation",)

# Headless bundled Chromium advertises a "HeadlessChrome" UA token and ships no
# sec-ch-ua client hints. Bot-defense vendors (PerimeterX, Akamai, DataDome) block
# that token on sight. We do NOT inject a synthetic fingerprint; we only normalize
# the engine-reported UA to its non-headless equivalent and emit coherent client
# hints derived from the live browser major version, so the headless engine looks
# like the same-version headful Chrome it actually is.
#
# Coherence rule: the UA platform string, the sec-ch-ua-platform header, and the
# native navigator.platform exposed by the engine MUST agree. We therefore key the
# UA template + client-hint platform off the HOST OS the browser runs on (Windows
# dev box vs Linux Docker in prod), never a fixed value.
HEADLESS_UA_TOKEN: str = "HeadlessChrome"
HEADFUL_UA_TOKEN: str = "Chrome"
DEHEADLESS_UA_FALLBACK_MAJOR: int = 145

# Per-host-OS UA templates. {major} is substituted with the resolved Chrome major
# version. Each template's OS string matches the corresponding CHROME_CLIENT_HINT
# platform label and the native navigator.platform for that OS.
DEHEADLESS_UA_TEMPLATE_BY_HOST_OS: dict[str, str] = {
    "windows": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    ),
    "macos": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    ),
    "linux": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    ),
}
CHROME_CLIENT_HINT_PLATFORM_BY_HOST_OS: dict[str, str] = {
    "windows": "Windows",
    "macos": "macOS",
    "linux": "Linux",
}
# Fallback when the host OS cannot be classified.
DEHEADLESS_HOST_OS_FALLBACK: str = "linux"

CHROME_CLIENT_HINT_GREASE_BRAND: str = "Not:A-Brand"
CHROME_CLIENT_HINT_GREASE_VERSION: str = "99"
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
    "BEHAVIOR_REALISM_ELIGIBLE_BROWSER_REASONS",
    "BROWSER_REQUIRED_REASONS",
    "CHROME_CLIENT_HINT_GREASE_BRAND",
    "CHROME_CLIENT_HINT_GREASE_VERSION",
    "CHROME_CLIENT_HINT_PLATFORM_BY_HOST_OS",
    "DEHEADLESS_HOST_OS_FALLBACK",
    "DEHEADLESS_UA_FALLBACK_MAJOR",
    "DEHEADLESS_UA_TEMPLATE_BY_HOST_OS",
    "HEADFUL_UA_TOKEN",
    "HEADLESS_UA_TOKEN",
    "NATIVE_REAL_CHROME_CONTEXT_OPTIONS",
    "REAL_CHROME_IGNORE_DEFAULT_ARGS",
    "RETRY_REASON_BROWSER_LABELS",
    "WARMUP_ELIGIBLE_BROWSER_REASONS",
    "WARMUP_VENDOR_BLOCK_PREFIX",
]
