from __future__ import annotations

PROXY_SECRET_REFS_KEY = "proxy_secret_refs"
PROXY_SECRET_REF_INDEX_KEY = "index"
PROXY_SECRET_REF_ENDPOINT_KEY = "endpoint"
PROXY_SECRET_REF_CIPHERTEXT_KEY = "ciphertext"
PROXY_SECRET_PAYLOAD_VERSION = 1
PROXY_PLAINTEXT_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "credential",
        "password",
        "proxy_password",
        "proxy_username",
        "secret",
        "token",
        "username",
    }
)
