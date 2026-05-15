# Plan: Job Aggregation Pipeline

**Created:** 2026-05-15
**Agent:** Opus
**Status:** TODO
**Touches buckets:** API + Bootstrap, Crawl Ingestion + Orchestration, Publish + Persistence, Config

## Goal

Aggregate job postings across multiple company career pages with stable posting identity, new/removed detection, user-configurable alert triggers, and aggregated export. Builds on top of the monitoring infrastructure from the Product Monitoring Pipeline plan. Single-user scope.

## Acceptance Criteria

- [ ] User can create a job monitor targeting multiple career page URLs
- [ ] System assigns stable identity to each job posting (URL-based)
- [ ] After each scheduled run, system detects new postings and removed postings vs previous snapshot
- [ ] User can configure trigger conditions (keyword filters, company filters) for which events matter
- [ ] Frontend shows monitored career pages, recent new/removed postings, and event history
- [ ] Aggregated CSV export includes posting status (new/active/removed) across monitor runs
- [ ] Reuses scheduling + retention infra from Product Monitoring Pipeline
- [ ] `python -m pytest tests -q` exits 0

## Do Not Touch

- `adapters/*` — job board adapters stay as-is (Greenhouse, Workday, LinkedIn, etc.)
- `listing_extractor.py` — extraction logic unchanged
- `data_enrichment/*` — job enrichment is Phase 2
- Auth system — single-user

## Dependencies

- **Requires:** Product Monitoring Pipeline (Slices 1-5 minimum) for `MonitorJob`, `MonitorEvent`, `MonitorSnapshot` models, scheduler service, and retention system.

## Slices

### Slice 1: Job Monitor Model Extensions
**Status:** TODO
**Files:**
- `backend/app/models/monitor.py` (extend)
- `backend/app/services/config/monitor_settings.py` (extend)
- `backend/alembic/versions/xxx_add_job_monitor_fields.py` (new migration)

**What:**
Extend `MonitorJob` or add `JobMonitorConfig` (JSONB in monitor.settings) with job-specific fields:
- `alert_triggers` (JSONB) — filter rules for which events fire:
  - `keywords` (list of strings — match against job title/description)
  - `companies` (list of strings — filter by company name if multi-company monitor)
  - `event_types` (list — which of `job_new`, `job_removed` to track)
- `posting_identity_mode` — default `url` (use posting URL as identity key)

Add `JobPostingState` model (or extend MonitorSnapshot):
- `id`, `monitor_id` (FK)
- `posting_url` (unique per monitor — the stable identity)
- `posting_title`, `company`, `location` (denormalized for quick display)
- `first_seen_at` (DateTime — when first detected)
- `last_seen_at` (DateTime — most recent run that included it)
- `removed_at` (DateTime, nullable — when first not seen)
- `status` (active, removed)
- `latest_data` (JSONB — full extracted fields from last seen run)

Config additions:
- `JOB_MONITOR_DEFAULT_TRACKED_FIELDS = ["title", "location", "salary_range", "employment_type"]`
- `JOB_POSTING_REMOVED_THRESHOLD_RUNS = 1` (how many consecutive misses before marking removed)

**Verify:** Migration runs. Models importable. `pytest tests -q` passes.

---

### Slice 2: Job Posting Identity + Lifecycle Tracking
**Status:** TODO
**Files:**
- `backend/app/services/job_monitor_service.py` (new)

**What:**
After a job-surface monitor run completes:
1. Load all `JobPostingState` rows for this monitor where `status = active`
2. Load current run's records (listing extraction results)
3. For each current record:
   - If URL exists in `JobPostingState` → update `last_seen_at`, update `latest_data`
   - If URL is new → create `JobPostingState` with `first_seen_at = now`, emit `job_new` MonitorEvent
4. For each active `JobPostingState` NOT in current records:
   - Mark `removed_at = now`, `status = removed`, emit `job_removed` MonitorEvent
5. Apply user's `alert_triggers` filter to events:
   - If keywords configured, only emit events where title/description matches
   - If companies configured, only emit events for matching companies
   - If event_types configured, only emit matching types

Reuse `MonitorEvent` from Plan 1 with `event_type` values: `job_new`, `job_removed`.

**Verify:** Create job monitor, run twice (second run missing one job). Confirm `job_removed` event created. Add new job in third run, confirm `job_new` event. Trigger filters work. `pytest tests -q` passes.

---

### Slice 3: Job Monitor API
**Status:** TODO
**Files:**
- `backend/app/api/monitors.py` (extend with job-specific endpoints)
- `backend/app/schemas/monitor.py` (extend)

**What:**
Additional endpoints (or extend existing monitor endpoints with surface-aware responses):
- `GET /api/monitors/{id}/postings` — paginated list of `JobPostingState` (active + recently removed), filterable by status/keyword
- `GET /api/monitors/{id}/postings/new` — postings first seen in the last N runs/days
- `GET /api/monitors/{id}/postings/removed` — recently removed postings
- `PATCH /api/monitors/{id}/triggers` — update alert trigger configuration

Response includes:
- Posting URL, title, company, location, salary_range, employment_type
- Status (active/removed)
- First seen / last seen / removed at timestamps
- Which run detected it

**Verify:** Endpoints return correct data. Filters work. `pytest tests -q` passes.

---

### Slice 4: Frontend — Job Monitor UI
**Status:** TODO
**Files:**
- `frontend/app/monitors/[id]/jobs/page.tsx` (new — or tab within monitor detail)
- `frontend/components/monitors/job-postings-table.tsx` (new)
- `frontend/components/monitors/job-monitor-config.tsx` (new)
- `frontend/lib/api/index.ts` (extend)
- `frontend/lib/api/types.ts` (extend)

**What:**
Within the monitor detail page (from Plan 1), add job-specific views:
- **Postings table** — sortable by first_seen, company, location, status. Color-code new (green) and removed (red).
- **Event timeline** — recent new/removed events with posting details
- **Trigger config panel** — edit keywords, companies, event type filters
- **Stats summary** — total active postings, new this week, removed this week

Monitor creation for job surface:
- URL input accepts multiple career page URLs
- Surface auto-set to job listing
- Tracked fields pre-filled with job defaults
- Trigger config section (keywords, event types)

**Verify:** UI renders. Job postings display correctly. Trigger config saves. New/removed badges show.

---

### Slice 5: Aggregated Job Feed Export
**Status:** TODO
**Files:**
- `backend/app/api/monitors.py` (extend)
- `backend/app/services/job_monitor_export.py` (new)

**What:**
Export endpoints for job monitors:
- `GET /api/monitors/{id}/export/postings.csv` — all active postings as CSV with columns: url, title, company, location, salary_range, employment_type, posted_date, first_seen, last_seen, status
- `GET /api/monitors/{id}/export/postings.json` — same as JSON array
- `GET /api/monitors/{id}/export/feed.csv` — recent events (new + removed) as a feed-style CSV with event_type, posting details, detected_at

Include status column so consumers can filter new/active/removed.

**Verify:** CSV well-formed. JSON valid. Status column correct. `pytest tests -q` passes.

---

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — add job monitor service, export
- [ ] `docs/BUSINESS_LOGIC.md` — add job posting identity and lifecycle decisions
- [ ] `docs/backend-architecture.md` — add job aggregation subsystem
- [ ] `docs/frontend-architecture.md` — add job monitor UI routes

## Notes

- Job monitors are a specialization of the generic monitor system. They share scheduling, retention, and event storage.
- Posting identity is URL-based only (no cross-source dedup per requirements).
- A posting is "removed" after 1 consecutive miss (configurable). This avoids false removals from transient extraction failures — can tune later.
- Job enrichment (seniority, skills, salary inference) is explicitly Phase 2.
- Existing job board adapters (Greenhouse, Workday, LinkedIn, etc.) handle extraction. This plan only adds the monitoring/tracking layer on top.
