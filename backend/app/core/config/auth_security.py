from __future__ import annotations

AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
AUTH_RATE_LIMIT_MAX_BUCKETS = 1024
AUTH_LOGIN_RATE_LIMIT = 10
AUTH_REGISTER_RATE_LIMIT = 5

# Migration-only limits for historical Passlib PBKDF2-SHA256 hashes. The upper
# bound prevents an attacker-controlled stored hash from consuming unbounded CPU.
LEGACY_PBKDF2_SHA256_MAX_HASH_LENGTH = 256
LEGACY_PBKDF2_SHA256_MAX_ROUNDS = 1_000_000
LEGACY_PBKDF2_SHA256_MAX_SALT_BYTES = 64
LEGACY_PBKDF2_SHA256_MIN_SALT_BYTES = 8

SECURITY_HEADER_CONTENT_TYPE_OPTIONS = "nosniff"
SECURITY_HEADER_FRAME_OPTIONS = "DENY"
SECURITY_HEADER_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURITY_HEADER_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"
SECURITY_HEADER_HSTS = "max-age=31536000; includeSubDomains"

API_ALLOWED_CORS_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

API_ALLOWED_CORS_HEADER_BASE = ("Content-Type", "Authorization", CSRF_HEADER_NAME)

AUTH_NO_STORE_PATH_PREFIXES = ("/api/auth/", "/api/crawls/")
PUBLIC_API_PATH_PREFIX = "/api/v1/"
CSV_UPLOAD_PATH = "/api/crawls/csv"
REQUEST_BODY_TOO_LARGE_DETAIL = "Request body too large"


def cors_allowed_headers(request_id_header: str) -> list[str]:
    normalized = (
        str(request_id_header or "").replace("\r", "").replace("\n", "").strip()
    )
    headers = list(API_ALLOWED_CORS_HEADER_BASE)
    if normalized and normalized not in headers:
        headers.append(normalized)
    return headers


def auth_rate_limit(identifier: str) -> int:
    return AUTH_LOGIN_RATE_LIMIT if identifier == "login" else AUTH_REGISTER_RATE_LIMIT


def auth_rate_limit_key(client_identifier: str, route_group: str) -> str:
    return f"auth:{route_group}:{client_identifier}"


def path_requires_no_store(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in AUTH_NO_STORE_PATH_PREFIXES)


def secure_transport_required(app_env: str) -> bool:
    normalized = str(app_env or "").strip().lower()
    return normalized not in {"", "development", "dev", "local", "test", "testing"}
