# Feature Spec: CrawlerAI MCP Server & Public API
**CrawlerAI — Product Feature Specification**
**Status:** Draft for Codex planning
**Scope:** MCP Server + REST API surface

---

## 1. Problem Statement

CrawlerAI today is a UI-driven tool. Developers building LLM shopping agents cannot call it programmatically mid-workflow — they have to use the dashboard manually, then pass results out themselves.

Two things are needed:

1. A **public REST API** that exposes CrawlerAI's core capabilities to external callers in a well-documented, versioned, authenticated way.
2. An **MCP Server** that wraps the public API as a set of typed MCP tools, so any MCP-compatible LLM agent (Claude, GPT-4, Cursor, etc.) can call CrawlerAI as infrastructure mid-thought.

These are separate layers. The MCP server is a thin adapter over the public API. The public API is the authoritative interface.

---

## 2. Goals

1. Allow developers to crawl, extract, and monitor any ecommerce page programmatically via REST API.
2. Allow LLM agents to call CrawlerAI tools via the Model Context Protocol without human involvement.
3. Keep the MCP server stateless and thin — all business logic stays in the backend.
4. Design the API for developer-first use: clear errors, typed responses, consistent field names, no surprise HTML in responses.

---

## 3. Non-Goals

- The MCP server does not handle authentication flows — API keys are configured at setup time by the developer.
- The public API does not expose internal admin or tenant-management endpoints.
- The MCP server does not implement ACP payment flows. It is a data and monitoring tool.

---

## 4. Public REST API

### 4.1 Versioning and Base URL

All endpoints are prefixed: `/api/v1/`

Version is in the URL path, not headers. Breaking changes increment the version.

### 4.2 Authentication

API key authentication via `Authorization: Bearer <api_key>` header.

API keys are generated and revoked from the CrawlerAI Console under Settings → API Keys. Each key is scoped to a user account and inherits that user's plan limits.

Rate limits are enforced per API key:
- Extraction endpoints: 60 requests / minute
- Watch endpoints: 600 requests / minute (lightweight reads)
- Burst allowance: 10x for 5 seconds

Standard rate limit headers returned on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.

### 4.3 Standard Response Envelope

All responses follow this structure:

**Success:**
```json
{
  "status": "ok",
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "duration_ms": 1240
  }
}
```

**Error:**
```json
{
  "status": "error",
  "error": {
    "code": "EXTRACTION_FAILED",
    "message": "Human-readable explanation",
    "details": { ... }
  },
  "meta": {
    "request_id": "uuid"
  }
}
```

Error codes are machine-readable strings, never raw HTTP status text.

---

### 4.4 Extraction Endpoints

#### `POST /api/v1/extract`

Crawl a single URL and return extracted structured data synchronously.

**Request:**
```json
{
  "url": "https://example.com/product/123",
  "surface": "ecommerce",
  "fields": ["price", "availability", "sku", "product_name", "images"],
  "options": {
    "use_cache": true,
    "max_wait_seconds": 30
  }
}
```

**Fields:**
- `url` — required. Must be a valid HTTP/HTTPS URL.
- `surface` — required. `"ecommerce"` in v1.
- `fields` — optional. If omitted, all fields for the surface are returned.
- `options.use_cache` — accepted in v1 but currently a no-op; public extraction always performs a fresh HTTP-only run.
- `options.max_wait_seconds` — client-specified timeout. Public launch caps this at 10 seconds.

**Response:**
```json
{
  "status": "ok",
  "data": {
    "url": "https://example.com/product/123",
    "surface": "ecommerce",
    "extracted_at": "2026-05-20T10:00:00Z",
    "crawl_method": "http",
    "fields": {
      "product_name": "Example Running Shoe",
      "price": 129.99,
      "currency": "USD",
      "availability": "in_stock",
      "sku": "ERS-BLK-10",
      "images": ["https://..."],
      "confidence": 0.94
    }
  }
}
```

All price values are returned as **numbers, not strings**. Currency is always a separate field. Availability is always a normalized string enum: `in_stock`, `out_of_stock`, `limited`, `unknown`.

**Error cases:**
- `BOT_BLOCK` — site refused the request and evasion failed
- `EXTRACTION_FAILED` — page loaded but target fields could not be extracted
- `TIMEOUT` — extraction exceeded `max_wait_seconds`
- `INVALID_SURFACE` — surface not supported for this URL type
- `URL_UNREACHABLE` — DNS failure or connection refused

---

#### `POST /api/v1/extract/batch`

Deferred in the lightweight public launch. The route validates the basic request shape and returns structured `WORKER_REQUIRED`; it does not create workers, durable batch rows, or background jobs.

**Request:**
```json
{
  "urls": ["https://...", "https://..."],
  "surface": "ecommerce",
  "fields": ["price", "availability"],
  "webhook_url": "https://your-server.com/crawlerai-results"
}
```

Maximum 100 URLs per batch.

**Response (immediate):**
```json
{
  "status": "ok",
  "data": {
    "batch_id": "uuid",
    "url_count": 2,
    "estimated_completion_seconds": 45
  }
}
```

**Polling:**
`GET /api/v1/extract/batch/{batch_id}` — returns status (`pending`, `processing`, `complete`, `partial`) and results for completed URLs.

If `webhook_url` was provided, CrawlerAI POSTs the full batch result to that URL on completion instead of requiring polling.

---

### 4.5 Watch (Delta Monitoring) Endpoints

These endpoints are part of the long-term public API shape, but they are deferred in the lightweight public launch. Routes return structured `WORKER_REQUIRED` until the Delta Engine worker deployment is approved.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/watches` | Create a watch |
| `GET` | `/api/v1/watches` | List watches |
| `GET` | `/api/v1/watches/{id}` | Get watch detail |
| `PATCH` | `/api/v1/watches/{id}` | Update watch |
| `DELETE` | `/api/v1/watches/{id}` | Delete watch |
| `GET` | `/api/v1/watches/{id}/history` | Delta history |
| `POST` | `/api/v1/watches/{id}/test` | Immediate test poll |

Full request/response schemas are defined in the Delta Engine spec. These endpoints are repeated here to mark them as part of the public API surface.

---

### 4.6 Domain Info Endpoint

#### `GET /api/v1/domains/{domain}`

Returns metadata about what CrawlerAI knows about a domain — whether it has been crawled before, what surface it was classified as, and whether cached selectors exist. Useful for developers to check if a domain will extract quickly (cache hit) or require a fresh crawl.

**Response:**
```json
{
  "status": "ok",
  "data": {
    "domain": "example.com",
    "known": true,
    "surface": "ecommerce",
    "last_crawled_at": "2026-05-18T08:00:00Z",
    "has_cached_selectors": true,
    "acquisition_profile": "http_preferred"
  }
}
```

`acquisition_profile` values: `http_preferred`, `browser_required`, `unknown`.

---

## 5. MCP Server

### 5.1 Overview

The MCP server is a lightweight process that exposes CrawlerAI's public API as MCP tools. It follows the MCP specification (JSON-RPC 2.0 over SSE or stdio transport).

It is stateless: it holds no database connections and no crawl state. Every tool call translates to one or more authenticated calls to the CrawlerAI public API.

### 5.2 Transport

The server supports both:
- **stdio** — for local developer use (Claude Desktop, Cursor, Claude Code)
- **HTTP + SSE** — for remote hosted deployment (accessible to cloud-hosted agents)

The hosted version is deployed as a standalone service. Developers configure their API key once during MCP server setup; it is not passed per-tool-call.

### 5.3 Configuration

On first run, the MCP server requires:
- `CRAWLERAI_API_KEY` — set via environment variable or config file
- `CRAWLERAI_API_BASE_URL` — defaults to `https://api.crawlerai.com/api/v1`

### 5.4 MCP Tools

---

#### Tool: `extract_product`

Extract structured product data from a single URL.

**Input schema:**
```json
{
  "url": { "type": "string", "description": "Product page URL to extract" },
  "fields": {
    "type": "array",
    "items": { "type": "string" },
    "description": "Fields to return. Defaults to all ecommerce fields.",
    "default": ["price", "availability", "sku", "product_name"]
  },
  "use_cache": {
    "type": "boolean",
    "description": "Return cached result if available. Faster but may be stale.",
    "default": false
  }
}
```

**Output:** Structured product data object. Price as number, availability as normalized enum.

**Example agent usage:**
> "What is the current price and stock status of this product? `extract_product(url='https://...')`"

---

#### Tool: `watch_product`

Register a price or availability watch on a URL with an optional condition.

**Input schema:**
```json
{
  "url": { "type": "string" },
  "condition": {
    "type": "string",
    "description": "Condition expression, e.g. 'price < 150' or 'availability == in_stock'",
    "default": null
  },
  "webhook_url": {
    "type": "string",
    "description": "URL to notify when condition is met."
  },
  "poll_interval_seconds": {
    "type": "integer",
    "description": "How often to check. Minimum 60.",
    "default": 300
  },
  "target_fields": {
    "type": "array",
    "items": { "type": "string" },
    "default": ["price", "availability"]
  }
}
```

**Output:** Watch object with `watch_id`, `status`, and `current_snapshot` (the values at time of creation).

**Example agent usage:**
> "Watch this URL and call my webhook if the price drops below $150. `watch_product(url='...', condition='price < 150', webhook_url='...')`"

---

#### Tool: `get_watch_status`

Get the current status and latest values for an existing watch.

**Input schema:**
```json
{
  "watch_id": { "type": "string" }
}
```

**Output:** Watch object including `status`, `last_known_values`, `last_checked_at`.

---

#### Tool: `cancel_watch`

Cancel and delete a watch.

**Input schema:**
```json
{
  "watch_id": { "type": "string" }
}
```

**Output:** Confirmation with `watch_id` and `cancelled_at` timestamp.

---

#### Tool: `list_watches`

List all active watches for the configured API key.

**Input schema:**
```json
{
  "status": {
    "type": "string",
    "enum": ["active", "paused", "triggered", "error"],
    "description": "Filter by status. Omit for all.",
    "default": null
  }
}
```

**Output:** Array of watch summary objects.

---

#### Tool: `check_domain`

Check if CrawlerAI has prior knowledge of a domain (affects extraction speed).

**Input schema:**
```json
{
  "domain": { "type": "string", "description": "Domain name, e.g. 'nike.com'" }
}
```

**Output:** Domain metadata — known, surface, last crawled, acquisition profile.

---

### 5.5 Error Handling in MCP Context

MCP tool errors must return structured error objects, not raw exceptions. Every tool must catch API errors and return them in the MCP error format with the `code` and `message` from the API error envelope. The agent must never receive a raw stack trace.

---

### 5.6 MCP Server Deployment

**Option A — Local (stdio)**

Developer installs the MCP server package and configures it in their MCP client (Claude Desktop, Cursor, etc.):

```json
{
  "mcpServers": {
    "crawlerai": {
      "command": "crawlerai-mcp",
      "env": {
        "CRAWLERAI_API_KEY": "your_key_here"
      }
    }
  }
}
```

**Option B — Hosted (HTTP + SSE)**

CrawlerAI hosts the MCP server at `mcp.crawlerai.ai`. Developers point their MCP client at this URL and authenticate with their API key. No local install required. This is the target for cloud-hosted agents like OpenAI Agents SDK and LangChain.

---

## 6. API Documentation Requirements

The public API must ship with:

- OpenAPI 3.1 spec — machine-readable, used to auto-generate client SDKs
- Hosted interactive docs (Swagger UI or Scalar) at `docs.crawlerai.ai/api`
- At least two code examples per endpoint: Python and JavaScript/Node
- All error codes documented with causes and recommended handling

---

## 7. SDK (Future, Not v1 Scope)

A Python SDK and a TypeScript SDK are the natural follow-ons once the API is stable. Not in scope for v1 — document the REST API first, build SDKs once the API surface is stable.

---

## 8. v1 Scope Boundary

| In Scope | Out of Scope |
|---|---|
| Single-URL synchronous extraction | Full site crawl via API |
| Batch extraction (async) | Sitemap discovery via API |
| Watch CRUD + webhook dispatch | Streaming/WebSocket push |
| MCP tools for extract + domain readiness | MCP tools for crawl studio config |
| Hosted + local MCP deployment | ACP payment flow integration |
| API key auth | OAuth / team-scoped tokens |
| Ecommerce surface only | Jobs / content surfaces |

---

## 9. Success Metrics

- `extract_product` p95 response time: < 5 seconds for domains with cached selectors
- `extract_product` p95 response time: < 30 seconds for unknown domains
- API error rate (5xx): < 0.5%
- MCP tool call success rate: ≥ 99% (excluding bot-block errors from target sites, which are domain errors not CrawlerAI errors)
- Time from API key creation to first successful `extract_product` call: < 5 minutes (developer onboarding speed)
