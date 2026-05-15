# Plan: Phase 2 — Multi-Tenant, Notifications, and Enrichment

**Created:** 2026-05-15
**Agent:** Opus
**Status:** TODO (blocked until Phase 1 plans complete)
**Touches buckets:** All

## Goal

Extend CrawlerAI from single-user tool to multi-tenant SaaS with webhook/email notifications, job enrichment, programmatic API access with keys, and scale infrastructure. This plan is a roadmap — slices will be detailed when Phase 1 (Product Monitoring + Job Aggregation) is verified complete.

## Prerequisites

- [ ] Product Monitoring Pipeline plan — DONE
- [ ] Job Aggregation Pipeline plan — DONE
- [ ] Both plans verified with passing tests

## Feature Groups

### Group A: Webhook Delivery

**What:** Push change events and job alerts to user-configured HTTP endpoints.

**Slices (high-level):**
1. `WebhookEndpoint` model — URL, secret (HMAC signing), event filters, retry config, status (active/disabled)
2. Webhook delivery Celery task — POST payload to endpoint, retry with exponential backoff (3 attempts), log delivery status
3. Webhook payload schema — standardized JSON envelope with event_type, monitor_id, timestamp, and event-specific data
4. Webhook management API — CRUD endpoints, test delivery (ping), delivery log
5. Frontend — webhook config UI per monitor, delivery history, test button
6. Signature verification docs — HMAC-SHA256 signing so consumers can verify authenticity

**Payload examples:**
```json
{
  "event": "field_changed",
  "monitor_id": 42,
  "timestamp": "2026-06-01T12:00:00Z",
  "data": {
    "url": "https://example.com/product/123",
    "field": "price",
    "old_value": "$29.99",
    "new_value": "$24.99"
  }
}
```

---

### Group B: Email Notifications

**What:** Send email alerts for monitor events based on user preferences.

**Slices (high-level):**
1. Email config — SMTP settings in env/config, sender address
2. `NotificationPreference` model — per-monitor email toggle, digest frequency (immediate/daily/weekly), event type filters
3. Email templates — HTML templates for: price change alert, new job posting, removed job posting, daily digest
4. Email delivery task — Celery task, rate-limited, with retry
5. Digest aggregation — daily/weekly summary of all events across monitors
6. Frontend — notification preferences UI per monitor

---

### Group C: Multi-Tenant Auth

**What:** Proper user isolation, org/team support, API keys for programmatic access.

**Slices (high-level):**
1. Tenant isolation — all queries scoped by user_id (already partially done), add org_id for team sharing
2. API key model — `ApiKey` table with hashed key, scopes (read/write/monitor), rate limits, expiry
3. API key auth middleware — authenticate requests via `Authorization: Bearer <api_key>` header alongside existing session auth
4. Rate limiting — per-key request limits (Redis-based)
5. Usage tracking — API call counts, monitor run counts per tenant for billing
6. Frontend — API key management page, usage dashboard

---

### Group D: Job Enrichment

**What:** Enrich job postings with inferred metadata using LLM + heuristics.

**Slices (high-level):**
1. Job enrichment service — parallel to existing data_enrichment but for job surface
2. Fields to enrich:
   - `seniority_level` (intern/junior/mid/senior/lead/director/vp/c-level) — inferred from title + description
   - `skills_tags` (list) — extracted technologies, tools, frameworks from description
   - `salary_estimate` — inferred range when not explicitly stated (based on title + location + seniority)
   - `remote_status` (remote/hybrid/onsite) — inferred from description + location
   - `industry_category` — classified from company + role
3. LLM prompt design — structured extraction prompts with fallback to heuristic regex
4. Enrichment trigger — on-demand per job monitor (like existing data enrichment jobs)
5. Enriched fields stored on `JobPostingState.enriched_data` (JSONB)
6. Frontend — enrichment toggle per job monitor, enriched fields visible in postings table

---

### Group E: Scale Infrastructure

**What:** Handle hundreds of monitors and thousands of URLs without choking single-worker Celery.

**Slices (high-level):**
1. Worker pool scaling — multiple Celery workers with concurrency config, priority queues (monitor runs vs on-demand runs)
2. Run batching — group monitor URLs by domain to respect rate limits and reuse browser sessions
3. Queue prioritization — on-demand user runs get priority over scheduled monitor runs
4. Database connection pooling — tune async session pool for concurrent monitor runs
5. Redis caching — cache recent snapshots for fast comparison, avoid DB reads on every diff
6. Monitoring/observability — Celery Flower or equivalent, run duration metrics, failure rate dashboards

---

### Group F: Additional Export Targets

**What:** Push data to external systems beyond download.

**Slices (high-level):**
1. Google Sheets integration — OAuth2 flow, push monitor snapshots/events to a user-linked sheet
2. Slack integration — post change alerts to a configured Slack channel via incoming webhook
3. Zapier/n8n webhook compatibility — ensure webhook payload schema works with popular automation tools
4. Scheduled email reports — attach CSV/JSON export to periodic email

---

## Prioritization (suggested order)

1. **Group A (Webhooks)** — highest value, enables all downstream integrations
2. **Group B (Email)** — most requested notification channel
3. **Group C (Multi-Tenant)** — required before any paid users
4. **Group D (Job Enrichment)** — value-add for job aggregation users
5. **Group F (Export Targets)** — nice-to-have integrations
6. **Group E (Scale)** — only needed when user count justifies it

## Do Not Touch (until relevant group starts)

- Existing single-user auth flow — until Group C
- Existing Celery single-worker setup — until Group E
- Existing data_enrichment subsystem — job enrichment is separate (Group D)

## Doc Updates Required

- [ ] All docs updated per group as each group completes
- [ ] New doc: `docs/WEBHOOK_SPEC.md` — payload schemas, signing, retry policy
- [ ] New doc: `docs/API_KEYS.md` — key format, scopes, rate limits
- [ ] Update `docs/ENGINEERING_STRATEGY.md` — multi-tenant isolation rules

## Notes

- Each group is independently shippable. Don't block on completing all groups.
- Webhooks (Group A) should be built immediately after Phase 1 since the event infrastructure already exists.
- Multi-tenant (Group C) is the gate for monetization — no paid users without proper isolation.
- Scale (Group E) is last because premature optimization. Single worker handles dozens of monitors fine.
