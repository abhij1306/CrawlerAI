from __future__ import annotations

ACCESS_DENIED_MARKER = "access denied"
ACCESS_FORBIDDEN_MARKER = "access forbidden"
SHAPE_SECURITY_MARKER = "shape security"

# Bot-vendor response header tokens. Each row is
# (header_name, required_value_substring, vendor); an empty substring matches
# header presence only. Consumed by acquisition header classification.
BOT_VENDOR_HEADER_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("x-datadome", "", "datadome"),
    ("x-datadome-cid", "", "datadome"),
    ("server", "datadome", "datadome"),
    ("cf-mitigated", "challenge", "cloudflare"),  # only when value = "challenge"
    ("x-sucuri-id", "", "sucuri"),
    ("x-sucuri-cache", "", "sucuri"),
    ("x-akamai-transformed", "", "akamai"),
    ("akamai-grn", "", "akamai"),
    ("x-px-block", "", "perimeterx"),
)

# Provider/active-provider marker tokens that identify Cloudflare challenge
# evidence. Consumed by browser challenge recovery and block detection.
CLOUDFLARE_PROVIDER_TOKENS: frozenset[str] = frozenset(
    {"cloudflare", "cf-challenge", "cf-browser-verification"}
)

# Fetch redirect policy (SSRF guard). Manual redirect followers in
# app/core/url_safety.py re-validate every Location target against the
# public-target rules before issuing the next request and cap chain length.
REDIRECT_FOLLOW_STATUS_CODES: frozenset[int] = frozenset({301, 302, 303, 307, 308})
MAX_VALIDATED_REDIRECTS = 5

BLOCK_SIGNATURES = {
    "phrases": [
        ACCESS_DENIED_MARKER,
        ACCESS_FORBIDDEN_MARKER,
        "access to this page has been denied",
        "robot or human",
        "are you a robot",
        "are you human",
        "not a robot",
        "you're not a robot",
        "please verify you are a human",
        "reddit - please wait for verification",
        "verify you are human",
        "complete the security check",
        "please complete the captcha",
        "px-captcha",
        "human verification",
        "enable javascript to view",
        "enable javascript and cookies",
        "you have been blocked",
        "this request was blocked",
        "sorry, you have been blocked",
        "checking your browser",
        "checking if the site connection is secure",
        "just a moment",
        "attention required",
        "pardon our interruption",
        "please turn javascript on",
        "why do i have to complete a captcha",
        "our systems have detected unusual traffic from your computer network",
        "this page checks to see if it's really you sending the requests",
    ],
    "active_provider_markers": [
        {"marker": "px-captcha", "provider": "perimeterx"},
        {"marker": "cf-challenge", "provider": "cloudflare"},
        {"marker": "cf-browser-verification", "provider": "cloudflare"},
        {"marker": "dd-modal", "provider": "datadome"},
        {"marker": "kpsdk", "provider": "kasada"},
        {"marker": "window.kpsdk", "provider": "kasada"},
        {"marker": "incapsula", "provider": "incapsula"},
        {"marker": "distil", "provider": "distil"},
        {"marker": SHAPE_SECURITY_MARKER, "provider": SHAPE_SECURITY_MARKER},
        {"marker": "arkose", "provider": "arkose"},
    ],
    "cdn_provider_markers": [
        {"marker": "perimeterx", "provider": "perimeterx"},
        {"marker": "cloudflare", "provider": "cloudflare"},
        {"marker": "akamai", "provider": "akamai"},
        {"marker": "akamaized", "provider": "akamai"},
        {"marker": "datadome", "provider": "datadome"},
        {"marker": "kasada", "provider": "kasada"},
    ],
    "provider_markers": [
        "perimeterx",
        "px-captcha",
        "cloudflare",
        "cf-challenge",
        "cf-browser-verification",
        "akamai",
        "akamaized",
        "datadome",
        "dd-modal",
        "kasada",
        "kpsdk",
        "incapsula",
        "distil",
        SHAPE_SECURITY_MARKER,
        "hcaptcha",
        "recaptcha",
        "g-recaptcha",
        "funcaptcha",
        "arkose",
    ],
    "browser_challenge_strong_markers": {
        "captcha": "captcha",
        "you're not a robot": "robot_gate",
        "verify you are human": "verification_text",
        "human verification": "human_verification",
        "checking your browser": "browser_check",
        "cf-browser-verification": "cloudflare_verification",
        "challenge-platform": "challenge_platform",
        "just a moment": "interstitial_text",
        "reddit - please wait for verification": "reddit_verification",
        ACCESS_DENIED_MARKER: "access_denied",
        ACCESS_FORBIDDEN_MARKER: "access_forbidden",
        "powered and protected by akamai": "akamai_banner",
        "hang tight! routing to checkout": "akamai_bot_failover",
        "datadome": "datadome_marker",
        "unusual traffic from your computer network": "google_unusual_traffic",
    },
    "content_tolerant_strong_markers": [
        "captcha",
    ],
    "browser_challenge_weak_markers": {
        "one more step": "generic_interstitial",
        "oops!! something went wrong": "generic_error_text",
        "error page": "error_page_text",
    },
    "title_regexes": [
        r"access\s+denied",
        r"access\s+forbidden",
        r"robot\s+or\s+human",
        r"you(?:'|’)?re\s+not\s+a\s+robot",
        r"human\s+verification",
        r"just\s+a\s+moment",
        r"reddit\s+-\s+please\s+wait\s+for\s+verification",
        r"attention\s+required",
        r"you\s+have\s+been\s+blocked",
        r"security\s+check",
        r"pardon\s+our\s+interruption",
        r"unusual\s+traffic",
        r"hang\s+tight!?\s+routing\s+to\s+checkout",
        r"site\s+maintenance",
        r"oops!?\s+something\s+went\s+wrong",
        r"something\s+went\s+wrong",
    ],
    "challenge_elements": {
        "iframe_src_markers": {
            "captcha-delivery.com": "captcha_delivery_iframe",
            "challenges.cloudflare.com": "cloudflare_turnstile_iframe",
        },
        "iframe_title_markers": {
            "captcha": "captcha_titled_iframe",
            "datadome": "datadome_titled_iframe",
        },
        "script_src_markers": {
            "captcha-delivery.com": "captcha_delivery_script",
            "datadome": "datadome_script",
            "kasada.io/ips.js": "kasada_ips_script",
            "/kpsdk/": "kasada_ips_script",
            "kp_uid": "kasada_ips_script",
        },
        "html_markers": {
            "geo.captcha-delivery.com": "captcha_delivery_host",
            "ct.captcha-delivery.com": "captcha_delivery_bootstrap",
            'title="datadome captcha"': "datadome_captcha_title",
            "window.kpsdk": "kasada_kpsdk_bootstrap",
        },
        "storage_state": {
            "cookie_name_prefixes": [
                "_px",
            ],
            "cookie_name_exact": [
                "__cf_bm",
                "_abck",
                "ak_bmsc",
                "bm_sz",
                "cf_clearance",
                "pxcts",
                "datadome",
            ],
            "cookie_value_tokens": [
                ACCESS_DENIED_MARKER,
                ACCESS_FORBIDDEN_MARKER,
                "bot_management",
                "captcha",
                "datadome",
            ],
            "local_storage_name_tokens": [
                "_px",
                "datadome",
            ],
            "local_storage_value_tokens": [
                ACCESS_DENIED_MARKER,
                ACCESS_FORBIDDEN_MARKER,
                "bot_management",
                "captcha",
                "datadome",
            ],
        },
    },
}
