 CrawlerAI Security Audit Report

**Repository:** [abhij1306/CrawlerAI](https://github.com/abhij1306/CrawlerAI)
**Audit Date:** May 21, 2026
**Auditor:** Perplexity AI (OWASP Top 10 + STRIDE framework)
**Scope:** Backend (FastAPI/Python), Frontend (Next.js), CI/CD pipelines, secrets management, auth flows

***

## Executive Summary

CrawlerAI has a well-structured codebase with several security-forward design decisions already in place — including a dedicated SSRF guard (`url_safety.py`), Gitleaks secret scanning in CI, token versioning for session invalidation, and proper use of `httponly` cookies. However, several significant gaps remain that need attention before this application handles production traffic with real user data. The most critical are: the missing `Secure` flag on the session cookie, use of PBKDF2 instead of bcrypt/argon2id for password hashing, no rate limiting on the `/api/auth/login` and `/api/auth/register` endpoints, and absence of security response headers across the API.

**Overall Risk Level: MEDIUM-HIGH**

***

## Findings Summary

| # | Severity | Category | Finding |
|---|----------|----------|---------|
| 1 | 🔴 HIGH | A07 – Auth Failures | Missing `Secure` flag on session cookie |
| 2 | 🔴 HIGH | A07 – Auth Failures | No rate limiting on `/api/auth/login` (brute-force vector) |
| 3 | 🟠 MEDIUM | A07 – Auth Failures | Password hashing uses PBKDF2-SHA256, not bcrypt/argon2id |
| 4 | 🟠 MEDIUM | A02 – Cryptographic Failures | JWT uses HS256 (symmetric), long 24h expiry, no refresh rotation |
| 5 | 🟠 MEDIUM | A05 – Misconfiguration | No security response headers (CSP, HSTS, X-Frame-Options, nosniff) |
| 6 | 🟠 MEDIUM | A05 – Misconfiguration | CORS uses `allow_methods=["*"]` and `allow_headers=["*"]` |
| 7 | 🟠 MEDIUM | A05 – Misconfiguration | Frontend `next.config.ts` has no security headers configured |
| 8 | 🟡 LOW | A06 – Vulnerable Components | CI has no dependency vulnerability scanner (no `pip-audit` or `npm audit`) |
| 9 | 🟡 LOW | A05 – Misconfiguration | No Dependabot / Renovate config for automated dependency updates |
| 10 | 🟡 LOW | A09 – Logging & Monitoring | Login failure events not distinctly logged for anomaly detection |
| 11 | ✅ PASS | A10 – SSRF | `url_safety.py` correctly blocks private/loopback IPs with DNS rebinding guard |
| 12 | ✅ PASS | A03 – Injection | SQLAlchemy ORM used throughout — no raw SQL concatenation found |
| 13 | ✅ PASS | Secrets | `.gitignore` covers `.env`, `*.pem`, `*.key`; Gitleaks runs in CI |
| 14 | ✅ PASS | A07 – Auth Failures | Token version invalidation on logout/role change present |
| 15 | ✅ PASS | A01 – Access Control | `require_admin` dependency correctly enforces role checks |

***

## Detailed Findings

### Finding 1 — Missing `Secure` Cookie Flag 🔴 HIGH

**File:** `backend/app/api/auth.py`, line with `response.set_cookie(...)`

**Current code:**
```python
response.set_cookie("access_token", token, httponly=True, samesite="lax")
```

The `Secure` flag is absent. Without it, the browser will transmit the session cookie over plain HTTP connections, enabling cookie theft via a network MITM or accidental HTTP redirect. The `samesite="lax"` (not `"strict"`) also permits the cookie to be sent on top-level cross-site navigations (e.g., OAuth redirects), which is acceptable — but `Secure` is non-negotiable.

**Fix:**
```python
response.set_cookie(
    "access_token",
    token,
    httponly=True,
    samesite="strict",       # Upgrade to strict for the login cookie
    secure=True,             # REQUIRED — only send over HTTPS
    max_age=int(settings.jwt_expire_hours * 3600),
    path="/",
)
```

Only omit `secure=True` in local `APP_ENV=development` to avoid breaking localhost development:
```python
secure = settings.app_env != "development"
response.set_cookie("access_token", token, httponly=True, samesite="lax" if not secure else "strict", secure=secure)
```

**OWASP:** A07 (Identification and Authentication Failures) — Cookie flags missing on session tokens

***

### Finding 2 — No Rate Limiting on Auth Endpoints 🔴 HIGH

**File:** `backend/app/api/auth.py` — `/api/auth/login` and `/api/auth/register`

Correction: the repo already has a global per-IP limiter in `backend/app/main.py` that applies to `/api/auth/*`; these routes are not fully unprotected. The real gap is that auth endpoints do not have a stricter auth-specific threshold than the generic limiter, so brute-force attempts can still consume the much broader default budget.

**Fix — Add a per-IP sliding-window limiter:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/login")
@limiter.limit("10/minute")   # 10 attempts per IP per minute
async def login(...):
    ...
```

Alternatively, implement the same token-bucket pattern already used in `rate_limit.py` and apply it to `/api/auth/login`. Also consider adding account-lockout after N consecutive failures (store failed attempt count in Redis with a TTL).

**OWASP:** A07 — Rate limit login endpoint, account lockout

***

### Finding 3 — PBKDF2-SHA256 Instead of bcrypt/argon2id 🟠 MEDIUM

**File:** `backend/app/core/security.py`

```python
from passlib.hash import pbkdf2_sha256

def hash_password(password: str) -> str:
    return pbkdf2_sha256.hash(password)
```

The OWASP checklist explicitly requires **bcrypt (work factor ≥ 12) or argon2id**. PBKDF2-SHA256 is not inherently broken but is significantly faster than bcrypt or argon2id on GPU hardware, making offline dictionary attacks cheaper. Passlib supports bcrypt and argon2 with a one-line swap.

**Fix:**
```python
from passlib.context import CryptContext

# bcrypt with work factor 12 (OWASP minimum)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False
```

Existing stored PBKDF2 hashes will be transparently re-hashed to bcrypt on next user login when `deprecated="auto"` is set. Add a migration note in CHANGELOG.

**OWASP:** A07 — Passwords must be hashed with bcrypt/argon2id, not PBKDF2

***

### Finding 4 — JWT HS256 With 24-Hour Expiry, No Refresh Token Rotation 🟠 MEDIUM

**File:** `backend/app/core/security.py` and `.env.example`

```python
jwt_algorithm: str = "HS256"
jwt_expire_hours: int = 24
```

Three issues:

1. **HS256 (symmetric)** means the same secret is used to both sign and verify tokens. If the secret leaks (e.g., via environment variable exposure), all tokens are compromised and cannot be revoked individually.
2. **24-hour access token lifetime** is far too long. OWASP recommends a 15-minute maximum for access tokens with a separate refresh token for renewal.
3. **No refresh token rotation** — there is no refresh endpoint. Users simply hold a 24-hour-valid JWT with no way for the server to revoke it before expiry (except bumping `token_version`, which voids all tokens for that user).

**Fix:**
- Switch to **RS256** (asymmetric) by generating an RSA key pair. Store only the private key server-side; verification uses the public key.
- Add a `/api/auth/refresh` endpoint that issues a new 15-minute access token against a 7-day `refresh_token` (httpOnly cookie).
- On each refresh, invalidate the old refresh token and issue a new one (rotation). Store refresh token hashes in Redis/DB with TTLs.
- Implement reuse detection: if a previously-used refresh token is presented, revoke the entire family.

For the near-term, at minimum reduce `JWT_EXPIRE_HOURS` to `1` and add a `Secure` cookie flag (see Finding 1).

**OWASP:** A07 — Access tokens short-lived; refresh tokens rotate on every use

***

### Finding 5 — No Security Response Headers on API 🟠 MEDIUM

**File:** `backend/app/main.py` — no security headers middleware found

The application has `CORSMiddleware` but no middleware adding any security headers. Missing headers:

| Missing Header | Risk |
|----------------|------|
| `Strict-Transport-Security` | SSL stripping / MITM downgrade |
| `X-Content-Type-Options: nosniff` | MIME sniffing attacks |
| `X-Frame-Options: DENY` | Clickjacking via iframe |
| `Content-Security-Policy` | XSS, resource hijacking |
| `Referrer-Policy` | Referrer URL leakage |
| `Cache-Control: no-store` | Sensitive data cached in shared proxies |

**Fix — Add a middleware to `main.py`:**
```python
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

app.add_middleware(SecurityHeadersMiddleware)
```

Add this **after** CORSMiddleware registration (Starlette applies middleware in reverse order).

**OWASP:** A05 — Harden configs; security headers on all API responses

***

### Finding 6 — CORS Overly Permissive (`allow_methods=["*"]`, `allow_headers=["*"]`) 🟠 MEDIUM

**File:** `backend/app/main.py`, lines 145–150

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),  # ✅ GOOD — uses an allowlist
    allow_credentials=True,
    allow_methods=["*"],                   # ❌ too broad
    allow_headers=["*"],                   # ❌ too broad
)
```

The `allow_origins` is correctly an allowlist (not `*`), which is the most critical part. However, `allow_methods=["*"]` permits `DELETE`, `PUT`, `PATCH`, and non-standard methods that may not be needed. Combined with `allow_credentials=True`, this maximizes the attack surface for CSRF (though `SameSite=Lax` provides some mitigation).

**Fix:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_frontend_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)
```

**OWASP:** A05 — CORS must not use wildcard methods/headers with `credentials=True`

***

### Finding 7 — Frontend Missing Security Headers in `next.config.ts` 🟠 MEDIUM

**File:** `frontend/next.config.ts`

```typescript
const nextConfig: NextConfig = {
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  typedRoutes: true,
};
```

Next.js supports adding security headers via `headers()` in the config. Currently none are set, meaning the frontend serves HTML pages without CSP, HSTS, `X-Frame-Options`, or `nosniff` headers.

**Fix:**
```typescript
const nextConfig: NextConfig = {
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  typedRoutes: true,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Strict-Transport-Security',
            value: 'max-age=31536000; includeSubDomains; preload',
          },
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline'",  // tighten after audit
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "connect-src 'self'",
              "object-src 'none'",
            ].join('; '),
          },
        ],
      },
    ];
  },
};
```

**OWASP:** A05 — Security headers set on all web responses

***

### Finding 8 — No Dependency Vulnerability Scanner in CI 🟡 LOW

**File:** `.github/workflows/backend-ci.yml`

The backend CI runs `ruff` and tests but does **not** include `pip-audit` or `safety` to scan for CVEs in Python dependencies. The frontend CI similarly has no `npm audit` step. Given the project pulls in Playwright, Anthropic SDK, SQLAlchemy, and other heavy dependencies, new CVEs are a realistic risk.

**Fix — Add to `backend-ci.yml`:**
```yaml
- name: Dependency vulnerability scan
  run: |
    pip install pip-audit
    pip-audit --strict --vulnerability-service osv
```

**Fix — Add to frontend CI:**
```yaml
- name: Dependency vulnerability scan
  run: npm audit --audit-level=high
  working-directory: frontend
```

Fail the build on HIGH/CRITICAL findings. This is distinct from Gitleaks (which scans for secrets, not CVEs).

**OWASP:** A06 — Dependency scanning in CI on every PR

***

### Finding 9 — No Dependabot / Renovate Config 🟡 LOW

**File:** `.github/` (no `dependabot.yml` present)

The repo has no automated dependency update mechanism. New CVEs in direct dependencies won't be surfaced as PRs.

**Fix — Create `.github/dependabot.yml`:**
```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/backend"
    schedule:
      interval: weekly
  - package-ecosystem: npm
    directory: "/frontend"
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: "/"
    schedule:
      interval: monthly
```

**OWASP:** A06 — Automated dependency updates via Renovate/Dependabot

***

### Finding 10 — Login Failures Not Distinctly Logged 🟡 LOW

**File:** `backend/app/services/auth_service.py`

`authenticate_user` returns `None` on failure and the caller raises `HTTP 401`. No structured log event is emitted on authentication failure, so anomaly detection (e.g., 50 failed logins for user X in 60 seconds) cannot be done from logs alone.

**Fix:**
```python
async def authenticate_user(...) -> tuple[str, User] | None:
    ...
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        logger.warning(
            "auth.login_failed",
            extra={"email": email.lower(), "reason": "bad_credentials"},
        )
        return None
    logger.info("auth.login_success", extra={"user_id": str(user.id)})
    return create_access_token(...), user
```

Pair this with an alerting rule on `auth.login_failed` frequency per `email` to detect credential stuffing.

**OWASP:** A09 — Structured audit logs; alerting on anomalies

***

## What Is Already Done Well ✅

### SSRF Protection (`url_safety.py`)
`validate_public_target()` performs DNS resolution and then checks every resolved IP against `ip_value.is_private`, `is_loopback`, `is_link_local`, `is_reserved`, and CGNAT ranges. This is a textbook SSRF guard and is correctly integrated before any HTTP fetch. The DNS rebinding protection (resolving *after* hostname validation) is correctly ordered.

### SQL Injection (A03)
The entire data access layer uses SQLAlchemy ORM with parameterized queries. No raw string-concatenated SQL was found.

### Secrets Not Committed (A02 / Secrets Management)
- `.gitignore` correctly excludes `.env`, `*.pem`, `*.key`, `*.db`, `*.sqlite`, and credential files.
- Gitleaks runs on every push and PR via `.github/workflows/gitleaks.yml`.
- `.env.example` uses placeholder values (`replace-with-64-byte-random-secret`), not real secrets.

### Token Version Invalidation
`token_version` is stored on the User model and embedded in the JWT payload (`"ver"` claim). `get_current_user` validates it on every request. This means calling a logout or role-change endpoint can invalidate all existing tokens for a user by bumping `token_version` — a clean server-side revocation mechanism.

### Admin Role Enforcement
`require_admin` is a FastAPI Dependency that raises `HTTP 403` if `user.role != "admin"`. This is applied to admin-only routes, correctly enforcing vertical access control.

### Input Validation via Pydantic
Route payloads use Pydantic schemas (`UserCreate`, etc.), ensuring input is validated at the API boundary before reaching business logic.

### Registration Disabled by Default
`REGISTRATION_ENABLED=false` in `.env.example` means open registration requires an explicit opt-in. This is a sensible default for a self-hosted crawling tool.

***

## STRIDE Threat Model Summary

| Data Flow | STRIDE Threats | Current Status |
|-----------|---------------|----------------|
| Browser → `/api/auth/login` | Spoofing (credential stuffing), DoS (brute-force) | ❌ No rate limiting |
| Login → JWT Cookie | Tampering (cookie theft over HTTP) | ❌ Missing `Secure` flag |
| JWT → `get_current_user` | Spoofing (forged/expired token) | ✅ `exp` validated; ⚠️ 24h too long |
| API → Database | Injection | ✅ ORM parameterized queries |
| API → External URLs (crawl target) | SSRF | ✅ `url_safety.py` blocks private IPs |
| API → Browser (responses) | Information Disclosure (headers) | ❌ No security headers |
| Frontend HTML → Browser | XSS, Clickjacking | ❌ No CSP/X-Frame-Options |
| CI → Dependencies | Supply chain (A06) | ⚠️ Gitleaks present; no CVE scan |

***

## Remediation Priority

| Priority | Action | Effort |
|----------|--------|--------|
| P0 — Do now | Add `secure=True` to session cookie | 1 line |
| P0 — Do now | Add rate limiting to `/api/auth/login` | ~20 lines (slowapi or custom) |
| P1 — This sprint | Add security headers middleware to FastAPI | ~15 lines |
| P1 — This sprint | Add security headers to `next.config.ts` | ~20 lines |
| P1 — This sprint | Restrict CORS `allow_methods` and `allow_headers` | 2 lines |
| P2 — Next sprint | Migrate password hashing to bcrypt (argon2id) | ~5 lines + migration note |
| P2 — Next sprint | Reduce JWT expiry to 1h; implement refresh token endpoint | ~80 lines |
| P2 — Next sprint | Add `pip-audit` and `npm audit` to CI | ~10 lines YAML |
| P3 — Backlog | Add Dependabot config | ~15 lines YAML |
| P3 — Backlog | Add structured login failure logging | ~5 lines |

***

*Audit based on OWASP Top 10 (2021), STRIDE threat modeling framework, and the Security skill reference guide.*
