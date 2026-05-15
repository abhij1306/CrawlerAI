# Plan: Product Monitoring Pipeline

**Created:** 2026-05-15
**Agent:** Opus
**Status:** TODO
**Touches buckets:** API + Bootstrap, Crawl Ingestion + Orchestration, Publish + Persistence, Config

## Goal

Turn one-shot crawl runs into recurring monitored jobs with user-defined scheduling, field-level change detection, rolling history retention, and a programmatic API for monitor data. Single-user scope — no multi-tenant auth.

## Acceptance Criteria

- [ ] User can create a monitor job targeting one or more URLs across multiple domains
- [ ] User can define schedule interval (every N hours/days) per monitor
- [ ] User can select which fields to track for changes (default: price)
- [ ] Scheduler dispatches crawl runs automatically on the defined interval
- [ ] After each run, system compares current vs previous records by URL identity and detects field-level diffs
- [ ] Change events are stored with timestamps and old/new values
- [ ] Historical snapshots auto-purge beyond user-defined retention window (max 90 days)
- [ ] REST API exposes monitor CRUD, history, current snapshot, and change events
- [ ] Frontend UI for monitor creation, history viewing, and configuration
- [ ] `python -m pytest tests -q` exits 0

## Do Not Touch

- `adapters/*` — extraction adapters are not changing
- `detail_extractor.py` / `listing_extractor.py` — extraction logic stays as-is
- `data_enrichment/*` — enrichment is separate; monitors track raw extracted fields
- `review/*` — selector/review workflow unchanged
- Auth system — single-user, no multi-tenant changes

## Slices

### Slice 1: Monitor Job Model + Config
**Status:** TODO
**Files:**
- `backend/app/models/monitor.py` (new)
- `backend/app/services/config/monitor_settings.py` (new)
- `backend/alembic/versions/xxx_add_monitor_tables.py` (new migration)

**What:**
Create `MonitorJob` model:
- `id`, `user_id`, `name` (user label)
- `urls` (JSONB list of target URLs)
- `domains` (JSONB list — derived from URLs)
- `surface` (ecommerce_detail, ecommerce_listing, etc.)
- `tracked_fields` (JSONB list — fields to diff, default `["price"]`)
- `schedule_interval_hours` (integer — how often to run)
- `retention_days` (integer — max 90, default 30)
- `settings` (JSONB — crawl settings to use, mirrors CrawlRun.settings shape)
- `requested_fields` (JSONB list — fields to extract)
- `status` (active, paused, archived)
- `last_run_at`, `next_run_at` (DateTime)
- `created_at`, `updated_at`

Create `MonitorEvent` model:
- `id`, `monitor_id` (FK)
- `run_id` (FK to CrawlRun, nullable)
- `source_url` (the URL that changed)
- `event_type` (field_changed, record_new, record_removed)
- `field_name` (which field changed, null for new/removed)
- `old_value` (JSONB)
- `new_value` (JSONB)
- `detected_at` (DateTime)

Create `MonitorSnapshot` model:
- `id`, `monitor_id` (FK)
- `run_id` (FK to CrawlRun)
- `snapshot_data` (JSONB — keyed by url_identity_key, values are tracked field values)
- `record_count` (integer)
- `created_at`

Config in `monitor_settings.py`:
- `MAX_RETENTION_DAYS = 90`
- `MIN_SCHEDULE_INTERVAL_HOURS = 1`
- `MAX_URLS_PER_MONITOR = 500`
- `MONITOR_STATUS_ACTIVE = "active"`
- `MONITOR_STATUS_PAUSED = "paused"`
- `MONITOR_STATUS_ARCHIVED = "archived"`

**Verify:** Migration runs clean. Models importable. `pytest tests -q` passes.

---

### Slice 2: Monitor CRUD API
**Status:** TODO
**Files:**
- `backend/app/api/monitors.py` (new)
- `backend/app/schemas/monitor.py` (new)
- `backend/app/main.py` (register router)

**What:**
API endpoints:
- `POST /api/monitors` — create monitor job
- `GET /api/monitors` — list monitors (with status filter)
- `GET /api/monitors/{id}` — get monitor detail (includes last run info, next scheduled)
- `PATCH /api/monitors/{id}` — update settings, schedule, tracked fields, pause/resume
- `DELETE /api/monitors/{id}` — archive (soft delete)
- `GET /api/monitors/{id}/events` — paginated change events
- `GET /api/monitors/{id}/history` — paginated snapshots with summary stats
- `GET /api/monitors/{id}/snapshot/current` — latest snapshot data

Pydantic schemas for request/response. Validate:
- `schedule_interval_hours >= 1`
- `retention_days` between 1-90
- `tracked_fields` non-empty
- `urls` non-empty, valid HTTP(S)

**Verify:** API endpoints respond correctly. Create/read/update/delete cycle works. `pytest tests -q` passes.

---

### Slice 3: Scheduler Service (Celery Beat)
**Status:** TODO
**Files:**
- `backend/app/services/monitor_scheduler.py` (new)
- `backend/app/tasks.py` (add periodic task)
- `backend/app/core/celery_app.py` (add beat schedule)

**What:**
Add Celery Beat periodic task `monitor.check_due_jobs` that runs every 5 minutes:
1. Query `MonitorJob` where `status = active` AND `next_run_at <= now()`
2. For each due monitor:
   - Create a `CrawlRun` using existing `create_crawl_run_from_payload` with the monitor's settings/URLs
   - Tag the run with `monitor_id` in settings (so we can link it back)
   - Update `last_run_at = now()`, `next_run_at = now() + interval`
   - Dispatch via existing `RunDispatcher`
3. For multi-URL monitors: create one run per URL (reuse batch pattern) or a single CSV-style run depending on surface

Celery Beat config:
```python
celery_app.conf.beat_schedule = {
    "monitor-check-due": {
        "task": "monitor.check_due_jobs",
        "schedule": 300.0,  # every 5 minutes
    },
}
```

**Verify:** Create a monitor with 1-hour interval. Confirm task picks it up and dispatches a run. `pytest tests -q` passes.

---

### Slice 4: Change Detection Engine
**Status:** TODO
**Files:**
- `backend/app/services/monitor_change_detection.py` (new)
- `backend/app/services/pipeline/core.py` (hook post-run callback for monitor runs)

**What:**
After a monitor-linked run completes (hook into existing run completion path):
1. Load the previous `MonitorSnapshot` for this monitor
2. Build current snapshot from completed run's records (keyed by `url_identity_key`)
3. Compare tracked fields between previous and current:
   - Field value changed → emit `field_changed` event
   - URL in current but not previous → emit `record_new` event
   - URL in previous but not current → emit `record_removed` event
4. Persist new `MonitorSnapshot`
5. Persist `MonitorEvent` rows for all detected changes
6. Update monitor's `result_summary` with change counts

Comparison logic:
- Normalize values before comparison (strip whitespace, lowercase for text; parse decimals for price)
- Only compare fields in `monitor.tracked_fields`
- Ignore records that failed extraction (no data)

**Verify:** Create monitor, run twice with different mock data. Confirm events generated correctly. `pytest tests -q` passes.

---

### Slice 5: Retention + Auto-Purge
**Status:** TODO
**Files:**
- `backend/app/services/monitor_retention.py` (new)
- `backend/app/tasks.py` (add periodic purge task)

**What:**
Add Celery Beat task `monitor.purge_expired_snapshots` (runs daily):
1. For each active monitor, delete `MonitorSnapshot` rows where `created_at < now() - retention_days`
2. Delete `MonitorEvent` rows older than retention window
3. Optionally delete orphaned `CrawlRun` + `CrawlRecord` rows tied to purged monitor snapshots (configurable — default: keep runs, delete only monitor-specific snapshot/event data)

Log purge stats.

**Verify:** Create snapshots older than retention. Run purge. Confirm deleted. `pytest tests -q` passes.

---

### Slice 6: Frontend — Monitor Management UI
**Status:** TODO
**Files:**
- `frontend/app/monitors/page.tsx` (new)
- `frontend/app/monitors/[id]/page.tsx` (new)
- `frontend/components/monitors/monitor-config.tsx` (new)
- `frontend/components/monitors/monitor-history.tsx` (new)
- `frontend/components/monitors/monitor-events.tsx` (new)
- `frontend/lib/api/index.ts` (add monitor API calls)
- `frontend/lib/api/types.ts` (add monitor types)
- `frontend/components/layout/app-shell.tsx` (add nav link)

**What:**
Pages:
- `/monitors` — list all monitors with status badges, last run time, next scheduled, change count since last visit
- `/monitors/[id]` — detail view with:
  - Config summary (URLs, schedule, tracked fields)
  - Recent events timeline (field changes, new/removed)
  - History chart (simple — tracked field values over time for each URL)
  - Pause/resume/archive controls
  - Edit settings modal

Monitor creation:
- Reuse crawl config patterns (URL input, surface selection, field selection)
- Add schedule interval picker
- Add tracked fields multi-select (from requested_fields + defaults)
- Add retention days slider (1-90)

**Verify:** UI renders. Create/edit/pause monitor works end-to-end. Events display after a completed run.

---

### Slice 7: Programmatic API for Monitor Data
**Status:** TODO
**Files:**
- `backend/app/api/monitors.py` (extend)

**What:**
Add export-oriented endpoints:
- `GET /api/monitors/{id}/export/events.json` — all events within retention window
- `GET /api/monitors/{id}/export/events.csv` — CSV of change events
- `GET /api/monitors/{id}/export/snapshot.json` — current snapshot as structured JSON
- `GET /api/monitors/{id}/export/history.json` — time-series of tracked field values per URL

These are the building blocks for future webhook/API-key access (Phase 2).

**Verify:** Endpoints return correct data. CSV is well-formed. `pytest tests -q` passes.

---

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — add monitor bucket (models, services, API, frontend)
- [ ] `docs/BUSINESS_LOGIC.md` — add monitor scheduling and change detection decisions
- [ ] `docs/backend-architecture.md` — add monitor subsystem section
- [ ] `docs/frontend-architecture.md` — add /monitors routes and components
- [ ] `docs/INVARIANTS.md` — add monitor scheduling contract (no silent schedule drift, retention enforced)

## Notes

- Celery Beat requires `celery -A app.core.celery_app beat` running alongside the worker. Document this in setup.
- Monitor runs reuse the full existing pipeline — no special extraction path.
- Change detection is post-hoc (after run completes), not real-time.
- Multi-domain monitors create separate runs per domain to respect domain memory scoping.
