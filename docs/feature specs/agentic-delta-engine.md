# Feature Spec: Agentic Delta Engine
**CrawlerAI — Product Feature Specification**
**Status:** Draft for Codex planning
**Scope:** Backend + Frontend

---

## 1. Problem Statement

Existing price monitoring tools — Price2Spy, Minderest, enterprise scraping APIs — solve the human-dashboard problem. A retail analyst logs in, sees a chart, and makes a manual decision.

The agentic commerce wave (ACP, AP2) requires a structurally different kind of monitoring: one where an autonomous LLM shopping agent can register a condition, receive a structured webhook when that condition is met, and immediately execute a checkout transaction — with no human in the loop.

CrawlerAI's existing extraction pipeline already produces clean, typed, field-level structured data. The Delta Engine is the scheduling, delta-detection, and webhook-dispatch layer built on top of it.

---

## 2. Goals

1. Allow users to register a **watch condition** on any crawlable URL — targeting specific extracted fields (price, availability, SKU).
2. Poll those URLs efficiently using the lightest possible acquisition path, using cached domain knowledge from previous crawls.
3. Detect field-level deltas between poll cycles.
4. Dispatch a **structured webhook** when a registered condition is met.
5. Expose monitoring controls as an **MCP tool** so LLM shopping agents can register and cancel watches programmatically.

---

## 3. Non-Goals

- This spec does NOT cover ACP/AP2 payment token generation. The Delta Engine fires a webhook. What the receiving agent does with it (initiate ACP checkout, log it, alert a user) is outside CrawlerAI's scope.
- Sub-second latency is NOT a requirement. 60-second minimum poll intervals are acceptable for the initial version.
- This spec does NOT introduce new extraction surfaces. It reuses the existing ecommerce surface extraction pipeline.

---

## 4. Core Concepts

### 4.1 Watch

A **Watch** is a persistent record representing one monitoring job. It has:

- `id` — unique identifier
- `url` — the product page URL to monitor
- `domain` — derived from URL, used to load cached domain config
- `surface` — always `ecommerce` in v1; extensible to other surfaces later
- `target_fields` — list of field names to monitor, e.g. `["price", "availability"]`
- `condition` — optional evaluation rule, e.g. `price < 150` or `availability == "in_stock"`
- `webhook_url` — destination for delta notifications
- `poll_interval_seconds` — how often to re-crawl, minimum 60s
- `status` — `active`, `paused`, `triggered`, `error`
- `last_checked_at` — timestamp of last poll
- `last_known_values` — snapshot of target field values from the most recent poll
- `created_at`, `updated_at`
- `tenant_id` / `user_id` — owner

### 4.2 Delta

A **Delta** is detected when the current extracted value of any `target_field` differs from its value in `last_known_values`. If a `condition` is set, a delta alone does not trigger the webhook — the condition must also evaluate to true.

### 4.3 Webhook Payload

When a condition is met, the engine dispatches a POST to `webhook_url` with the following structured payload:

```json
{
  "watch_id": "string",
  "url": "string",
  "triggered_at": "ISO8601 timestamp",
  "condition": "string | null",
  "delta": {
    "field": "price",
    "previous_value": "149.99",
    "current_value": "129.99",
    "currency": "USD"
  },
  "current_snapshot": {
    "price": "129.99",
    "availability": "in_stock",
    "sku": "ABC-123",
    "product_name": "Example Product"
  },
  "source_url": "string",
  "crawl_method": "http | browser"
}
```

This payload is intentionally typed and flat. No raw HTML, no DOM dumps. An LLM agent can consume it with zero re-parsing.

---

## 5. Acquisition Strategy for Polling

Each poll must be as lightweight as possible. The engine must apply the following priority order when re-acquiring data for a watch:

1. **JSON-LD / structured data in HTML** — if the domain has a known JSON-LD path from a previous crawl, hit it directly. No browser, no rendering.
2. **XHR / internal API endpoint** — if a previous crawl discovered an internal product API endpoint (e.g. `/api/products/{id}`), poll that endpoint directly. Minimal payload, no rendering.
3. **HTTP + CSS selectors from cache** — if cached selectors exist for this domain and surface, send a plain HTTP request and extract only the target fields using cached selectors. No browser.
4. **Browser (Playwright)** — only if steps 1–3 fail or if the domain is flagged as requiring JS rendering. Browser acquisition is the expensive fallback, not the default.

The poll must NOT re-run the full discovery or sitemap crawl. It is a targeted point-extraction on a single known URL using the minimum viable acquisition path.

---

## 6. Scheduling Architecture

- Watches are scheduled as recurring background jobs using the existing Celery infrastructure.
- Each watch spawns a Celery periodic task bound to its `poll_interval_seconds`.
- The task runs the acquisition strategy above, extracts target fields, compares against `last_known_values`, evaluates the condition, and dispatches the webhook if triggered.
- Scheduling must be dynamic: creating, pausing, resuming, or deleting a watch must update the Celery schedule without requiring a worker restart.
- Failed polls (network error, bot block, extraction failure) increment an error counter. After N consecutive failures (configurable, default 5), the watch status moves to `error` and the user is notified.
- Successful polls always update `last_known_values` and `last_checked_at`, even if no condition was triggered.

---

## 7. Condition Evaluation

Conditions are simple expressions evaluated against the extracted field values at poll time.

Supported operators in v1: `<`, `>`, `<=`, `>=`, `==`, `!=`

Supported field types in v1: `price` (numeric), `availability` (string enum)

Examples:
- `price < 150`
- `availability == "in_stock"`
- `price <= 99.99 AND availability == "in_stock"`

Condition parsing must be sandboxed and must never execute arbitrary code. A simple expression evaluator is sufficient — no full scripting engine required.

If no condition is set, any delta in any target field triggers the webhook.

---

## 8. API Endpoints

All endpoints require authentication.

### `POST /watches`
Create a new watch.

**Request body:**
```json
{
  "url": "string",
  "target_fields": ["price", "availability"],
  "condition": "price < 150",
  "webhook_url": "https://...",
  "poll_interval_seconds": 300
}
```

**Response:** Watch object.

**Behavior:** Runs an immediate first poll to validate the URL is crawlable and populate `last_known_values`. If the URL cannot be crawled, return a 422 with a descriptive error.

---

### `GET /watches`
List all watches for the authenticated user. Supports filtering by `status`.

---

### `GET /watches/{watch_id}`
Get a single watch including its current `last_known_values` and `status`.

---

### `PATCH /watches/{watch_id}`
Update a watch. Supports updating `condition`, `webhook_url`, `poll_interval_seconds`, and `status` (to pause/resume).

---

### `DELETE /watches/{watch_id}`
Delete a watch and cancel its scheduled polling job.

---

### `GET /watches/{watch_id}/history`
Return a paginated log of all deltas detected for this watch, whether or not they triggered the webhook (i.e., condition not met but a value changed).

---

### `POST /watches/{watch_id}/test`
Trigger an immediate one-off poll and return the result without firing the webhook. Used to verify the watch is configured correctly.

---

## 9. Frontend — Monitors Tab

The existing Monitors tab in the CrawlerAI Console should be extended with the following UI:

### 9.1 Watch Creation Form

Fields:
- **URL** — product page URL (validated on blur with a lightweight reachability check)
- **Fields to Monitor** — multi-select checkboxes: `price`, `availability`, `sku`. Default: `price` + `availability`.
- **Condition** — optional free-text field with inline syntax hint. Placeholder: `e.g. price < 150`
- **Poll Interval** — dropdown: 1 min / 5 min / 15 min / 30 min / 1 hour. Default: 5 min.
- **Webhook URL** — text input. Optional — if empty, deltas are stored but no outbound notification is sent.

### 9.2 Watch List View

Each watch row displays:
- URL (truncated, with favicon)
- Monitored fields
- Current values (live, fetched on page load)
- Status badge: `Active` / `Paused` / `Triggered` / `Error`
- Last checked timestamp
- Actions: Pause / Resume / Test / Delete

### 9.3 Watch Detail View

Clicking a watch opens a detail panel showing:
- Full configuration
- Delta history timeline — each detected change shown as a before/after diff on the changed field
- Webhook delivery log — timestamp, response code, payload preview

### 9.4 Status Handling

- `Error` status watches are highlighted in the list with an inline error message explaining the last failure (e.g. "Bot block detected", "Selector stale — domain may have changed layout").
- Users can manually trigger a re-test from the error state.

---

## 10. Rate Limits and Constraints

- Maximum watches per user: 50 (configurable per plan tier)
- Minimum poll interval: 60 seconds
- Maximum target fields per watch: 5
- Webhook delivery timeout: 10 seconds. On timeout or non-2xx response, retry with exponential backoff up to 3 times.
- Webhook payload max size: 10KB (sufficient for the structured payload above)

---

## 11. Data Retention

- `last_known_values` — always current, overwritten each poll
- Delta history — retained for 90 days
- Webhook delivery log — retained for 30 days

---

## 12. v1 Scope Boundary

| In Scope | Out of Scope |
|---|---|
| Ecommerce surface only | Jobs, content, forum surfaces |
| Single URL per watch | Bulk URL / category-level watching |
| Simple expression conditions | Complex multi-condition scripting |
| Outbound webhook dispatch | Inbound ACP payment token generation |
| HTTP + cached-selector polling | New domain discovery during poll |
| Celery-based scheduling | Event-driven / WebSocket streaming |

---

## 13. Success Metrics

- Poll acquisition uses browser (Playwright) on fewer than 20% of poll cycles (proxy for lightweight polling efficiency)
- Webhook delivery success rate ≥ 95%
- Median time from condition met → webhook delivered: < 5 seconds
- Watch creation to first successful poll: < 30 seconds
