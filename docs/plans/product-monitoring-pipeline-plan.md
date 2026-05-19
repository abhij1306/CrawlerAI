# Plan: Product Monitoring Pipeline

**Created:** 2026-05-19
**Agent:** Codex
**Status:** IN PROGRESS — implementation complete; broad backend verify has unrelated pre-existing failures
**Touches buckets:** API + Bootstrap, Crawl Ingestion + Orchestration, Publish + Persistence, Config

## Goal

Turn one-shot crawl runs into recurring monitored jobs with user-defined scheduling,
field-level change detection, rolling history retention, and a programmatic API for
monitor data. Single-user scope — no multi-tenant auth.

---

## Scheduler: Dev Mode vs Production Mode

The scheduler is built with a hard interface boundary so local dev and production
differ only in which driver invokes the same underlying service logic. The service
itself has no Celery or Redis imports.

```
┌──────────────────────────────────────────────────────────┐
│              MonitorSchedulerService                     │
│  check_due_jobs()  — pure async, no Celery dependency   │
│  dispatch_monitor() — calls existing RunDispatcher       │
│  pre_check_url()   — HTTP HEAD / ETag check              │
└───────────┬──────────────────────┬───────────────────────┘
            │                      │
   DEV MODE │              PROD MODE
            ▼                      ▼
  AsyncSchedulerLoop        Celery Beat Task
  (FastAPI lifespan,        (monitor.check_due_jobs)
   asyncio.sleep loop,       schedule: every 300s
   no Redis required)        requires: redis + worker
```

Dev mode is the default when `SCHEDULER_DRIVER` is unset or set to `dev`.
Set `SCHEDULER_DRIVER=celery` in `.env` to activate production mode.
The service logic is identical in both paths.

---

## Acceptance Criteria

- [x] User can create a monitor job targeting one or more URLs across multiple domains
- [x] User can define schedule interval (every N hours/days) per monitor
- [x] User can select which fields to track for changes (default: price)
- [x] Monitor jobs have a priority tier (`on_demand` / `priority` / `background`) controlling dispatch order
- [x] Scheduler performs HTTP HEAD pre-check before dispatching a full crawl; skips dispatch if page is unchanged
- [x] Scheduler dispatches crawl runs automatically on the defined interval
- [x] On-demand trigger available via `POST /api/monitors/{id}/run/now`
- [x] After each run, system compares current vs previous records by URL identity and detects field-level diffs
- [x] Change events are stored with timestamps and old/new values
- [x] Historical snapshots auto-purge beyond user-defined retention window (max 90 days)
- [x] REST API exposes monitor CRUD, history, current snapshot, and change events
- [x] Frontend UI for monitor creation, history viewing, and configuration
- [x] Dev mode works with `SCHEDULER_DRIVER=dev` — no Celery Beat, no Redis required
- [x] Production mode works with `SCHEDULER_DRIVER=celery` — existing Celery + Redis stack
- [ ] `python -m pytest tests -q` exits 0 — latest run on 2026-05-19: 5 unrelated failures outside monitor pipeline

---

## Do Not Touch

- `adapters/*` — extraction adapters are not changing
- `detail_extractor.py` / `listing_extractor.py` — extraction logic stays as-is
- `data_enrichment/*` — enrichment is separate; monitors track raw extracted fields
- `review/*` — selector/review workflow unchanged
- Auth system — single-user, no multi-tenant changes
- `pipeline/run_complete_callbacks.py` body — monitor hook is additive only (one callback registration point, nothing else)

---

## Slices

---

### Slice 1: Monitor Job Model + Config
**Status:** DONE
**Files:**
- `backend/app/models/monitor.py` (new)
- `backend/app/services/config/monitor_settings.py` (new)
- `backend/alembic/versions/xxx_add_monitor_tables.py` (new migration)

**What:**

Create `MonitorJob` model:
- `id`, `name` (user label)
- `urls` (JSONB list of target URLs)
- `domains` (JSONB list — derived from URLs)
- `surface` (ecommerce_detail, ecommerce_listing, etc.)
- `tracked_fields` (JSONB list — fields to diff, default `["price"]`)
- `schedule_interval_hours` (integer)
- `priority` (enum: `on_demand` / `priority` / `background`, default `background`)
- `retention_days` (integer — max 90, default 30)
- `settings` (JSONB — crawl settings, mirrors CrawlRun.settings shape)
- `requested_fields` (JSONB list)
- `status` (active, paused, archived)
- `last_run_at`, `next_run_at` (DateTime)
- `created_at`, `updated_at`

Create `MonitorEvent` model:
- `id`, `monitor_id` (FK)
- `run_id` (FK to CrawlRun, nullable)
- `source_url`
- `event_type` (field_changed, record_new, record_removed)
- `field_name` (null for new/removed events)
- `old_value` (JSONB)
- `new_value` (JSONB)
- `detected_at` (DateTime)
- `notified_at` (DateTime, nullable)
- `notification_status` (enum: `pending` / `sent` / `skipped`, default `pending`)

Create `MonitorSnapshot` model:
- `id`, `monitor_id` (FK)
- `run_id` (FK to CrawlRun)
- `snapshot_data` (JSONB — summary metadata only)
- `record_count` (integer)
- `change_count` (integer — total events detected in this snapshot cycle)
- `created_at`

Create `MonitorSnapshotRecord` model (one row per URL per snapshot):
- `id`, `snapshot_id` (FK to MonitorSnapshot)
- `monitor_id` (FK — for direct querying without snapshot join)
- `source_url`
- `url_identity_key`
- `field_values` (JSONB — tracked field values at this point in time)
- `created_at`

Create `MonitorURLState` model (one row per `(monitor_id, url)`):
- `id`, `monitor_id` (FK), `url`
- `last_etag` (string, nullable)
- `last_modified` (string, nullable)
- `last_content_hash` (string, nullable)
- `last_checked_at` (DateTime)
- `last_changed_at` (DateTime, nullable)
- `consecutive_unchanged_count` (integer, default 0)
- `auto_downgraded` (boolean, default False)

State rows are created automatically when a monitor is created (one per URL).

Config in `monitor_settings.py` — all constants live here, nowhere else:
```python
MAX_RETENTION_DAYS = 90
MIN_SCHEDULE_INTERVAL_HOURS = 1
MAX_URLS_PER_MONITOR = 500
MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK = 20
SCHEDULER_POLL_INTERVAL_SECONDS = 300
SCHEDULER_DRIVER_DEV = "dev"
SCHEDULER_DRIVER_CELERY = "celery"
HEAD_CHECK_TIMEOUT_SECONDS = 5
MONITOR_STATUS_ACTIVE = "active"
MONITOR_STATUS_PAUSED = "paused"
MONITOR_STATUS_ARCHIVED = "archived"
MONITOR_PRIORITY_ON_DEMAND = "on_demand"
MONITOR_PRIORITY_PRIORITY = "priority"
MONITOR_PRIORITY_BACKGROUND = "background"
NOTIFICATION_STATUS_PENDING = "pending"
NOTIFICATION_STATUS_SENT = "sent"
NOTIFICATION_STATUS_SKIPPED = "skipped"
```

**Verify:** Migration runs clean. All models importable. `MonitorURLState` rows created on monitor creation. `pytest tests -q` passes.

---

### Slice 2: Monitor CRUD API
**Status:** DONE
**Files:**
- `backend/app/api/monitors.py` (new)
- `backend/app/schemas/monitor.py` (new)
- `backend/app/main.py` (register router — one line)

**What:**

Endpoints:
- `POST /api/monitors` — create monitor job
- `GET /api/monitors` — list monitors (filterable by status, priority)
- `GET /api/monitors/{id}` — detail (includes last run, next scheduled, change count)
- `PATCH /api/monitors/{id}` — update settings, schedule, tracked fields, pause/resume
- `DELETE /api/monitors/{id}` — soft-delete (sets status = archived)
- `GET /api/monitors/{id}/events` — paginated change events (filterable by event_type, field_name)
- `GET /api/monitors/{id}/history` — paginated snapshots with per-snapshot change counts
- `GET /api/monitors/{id}/snapshot/current` — latest `MonitorSnapshotRecord` rows for this monitor

Pydantic validation:
- `schedule_interval_hours >= MIN_SCHEDULE_INTERVAL_HOURS`
- `retention_days` in range `[1, MAX_RETENTION_DAYS]`
- `tracked_fields` non-empty list
- `urls` non-empty, all valid `http(s)://` URLs
- `priority` must be one of the three enum values

**Verify:** Full CRUD cycle works. Validation rejects bad input. `pytest tests -q` passes.

---

### Slice 3: Scheduler Service (Dev Mode + Celery Prod Mode)
**Status:** DONE
**Files:**
- `backend/app/services/monitor_scheduler_service.py` (new)
- `backend/app/services/monitor_async_loop.py` (new)
- `backend/app/tasks.py` (add Celery task — wired but inactive in dev)
- `backend/app/core/celery_app.py` (add beat schedule — inactive unless `SCHEDULER_DRIVER=celery`)
- `backend/app/main.py` (add lifespan hook)

**What:**

#### `MonitorSchedulerService` (driver-agnostic core)

```python
class MonitorSchedulerService:
    async def check_due_jobs(self) -> None:
        """
        Single scheduler tick. Called by either the dev loop or Celery Beat.
        1. Query MonitorJob where status=active AND next_run_at <= now()
        2. Order by priority: on_demand first, priority second, background last
        3. Cap background + priority dispatches at MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK
           (on_demand jobs are never capped)
        4. For each due monitor: call pre_check_url() for each URL
        5. Skip URLs where pre_check returns unchanged; update MonitorURLState
        6. Dispatch CrawlRun only for URLs that changed or have no prior state
        7. Update last_run_at, next_run_at on the MonitorJob
        """

    async def pre_check_url(self, url: str, state: MonitorURLState) -> bool:
        """
        HTTP HEAD request, timeout = HEAD_CHECK_TIMEOUT_SECONDS.
        Returns True if page has changed (or no prior state exists).
        Compares ETag, then Last-Modified, then falls back to content hash.
        Updates MonitorURLState regardless of result.
        On HEAD failure or 405: return True (proceed with full crawl — never skip silently).
        """

    async def dispatch_monitor_run(self, monitor: MonitorJob, urls: list[str]) -> str:
        """
        Creates CrawlRun via existing create_crawl_run_from_payload.
        Tags run settings with {"monitor_id": monitor.id}.
        Returns run_id.
        """
```

#### Dev Mode Driver (`monitor_async_loop.py`)

```python
class AsyncSchedulerLoop:
    """
    Runs MonitorSchedulerService.check_due_jobs() on a fixed interval.
    Started as a FastAPI lifespan background task.
    No Redis, no Celery, no external dependencies.
    Intentionally simple — dev harness only. Do not add retry logic or
    persistence here; those concerns belong in MonitorSchedulerService.
    """
    def __init__(self, service: MonitorSchedulerService, interval_seconds: int):
        self._service = service
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._last_purge_at: datetime | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await self._service.check_due_jobs()
            await self._maybe_purge()
            await asyncio.sleep(self._interval)

    async def _maybe_purge(self) -> None:
        now = datetime.utcnow()
        if self._last_purge_at is None or (now - self._last_purge_at).total_seconds() >= 86400:
            await MonitorRetentionService().purge_expired()
            self._last_purge_at = now
```

FastAPI lifespan (add to `main.py`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SCHEDULER_DRIVER == SCHEDULER_DRIVER_DEV:
        loop = AsyncSchedulerLoop(
            MonitorSchedulerService(),
            SCHEDULER_POLL_INTERVAL_SECONDS
        )
        await loop.start()
    yield
    if settings.SCHEDULER_DRIVER == SCHEDULER_DRIVER_DEV:
        await loop.stop()
```

#### Celery Prod Driver (wired, inactive in dev)

```python
# backend/app/tasks.py
@celery_app.task(name="monitor.check_due_jobs")
def celery_check_due_jobs():
    asyncio.run(MonitorSchedulerService().check_due_jobs())

@celery_app.task(name="monitor.purge_expired_snapshots")
def celery_purge_expired():
    asyncio.run(MonitorRetentionService().purge_expired())

# backend/app/core/celery_app.py
if settings.SCHEDULER_DRIVER == SCHEDULER_DRIVER_CELERY:
    celery_app.conf.beat_schedule = {
        "monitor-check-due": {
            "task": "monitor.check_due_jobs",
            "schedule": SCHEDULER_POLL_INTERVAL_SECONDS,
        },
        "monitor-purge": {
            "task": "monitor.purge_expired_snapshots",
            "schedule": 86400.0,
        },
    }
```

**Verify:**
- `SCHEDULER_DRIVER=dev`: `uvicorn` starts without Redis or Celery running. Scheduler loop fires and logs within first poll interval.
- Create monitor with 1-hour interval. Confirm job picked up and CrawlRun dispatched within 5 minutes.
- Thundering herd test: Insert 50 monitors all with `next_run_at = now()` and priority `background`. Assert dispatch count in one tick `<= MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK`.
- HEAD pre-check test: URL returns same ETag on two successive ticks. Assert second tick skips full crawl dispatch.
- `pytest tests -q` passes.

---

### Slice 4: On-Demand Run Endpoint
**Status:** DONE
**Files:**
- `backend/app/api/monitors.py` (extend — add one endpoint)

**What:**

```
POST /api/monitors/{id}/run/now
```

Behavior:
- Validates monitor exists and is not archived
- Calls `MonitorSchedulerService.dispatch_monitor_run(monitor, monitor.urls)` directly — bypasses scheduler queue entirely
- Does NOT run HEAD pre-check (on-demand means the user wants fresh data now)
- Does not update `next_run_at` — scheduled runs continue unaffected
- Returns `{"run_id": "<id>", "dispatched_at": "<iso>", "url_count": N}`

**Verify:**
- Endpoint returns a valid `run_id` within 2 seconds.
- Dispatched `CrawlRun` has `monitor_id` in settings.
- `next_run_at` on the monitor is unchanged after call.
- `pytest tests -q` passes.

---

### Slice 5: Change Detection Engine
**Status:** DONE
**Files:**
- `backend/app/services/monitor_change_detection.py` (new)
- `backend/app/services/pipeline/run_complete_callbacks.py` (one additive change only — callback registration point)

**What:**

#### Hook Contract in `core.py`

Add exactly one callback registration point. No other monitor logic in `core.py`:

```python
_run_complete_callbacks: list[Callable[[str], Awaitable[None]]] = []

def register_run_complete_callback(cb: Callable[[str], Awaitable[None]]) -> None:
    _run_complete_callbacks.append(cb)

async def _on_run_complete(run_id: str) -> None:
    for cb in _run_complete_callbacks:
        await cb(run_id)
```

`MonitorChangeDetection` registers itself at app startup. Non-monitor runs pass
through with a no-op (`monitor_id` not in settings → early return inside the callback).

#### Change Detection Logic (`monitor_change_detection.py`)

```python
async def handle_run_complete(self, run_id: str) -> None:
    run = await get_run(run_id)
    monitor_id = run.settings.get("monitor_id")
    if not monitor_id:
        return

    monitor = await get_monitor(monitor_id)
    prev_records = await get_latest_snapshot_records(monitor_id)
    current_records = await get_run_records(run_id)

    previous = {r.url_identity_key: r for r in prev_records}
    current = {r.url_identity_key: r for r in current_records if r.data}

    events = []
    for key, record in current.items():
        if key not in previous:
            events.append(build_event("record_new", record))
        else:
            for field in monitor.tracked_fields:
                old_val = normalize(previous[key].field_values.get(field))
                new_val = normalize(record.data.get(field))
                if old_val != new_val:
                    events.append(build_event("field_changed", record, field, old_val, new_val))

    for key in previous:
        if key not in current:
            events.append(build_event("record_removed", previous[key]))

    await save_snapshot_and_events(monitor, run, current, events)
    await update_monitor_result_summary(monitor_id, len(events))
```

Normalization rules:
- Text fields: `strip().lower()`
- Price fields: parse to `Decimal`, compare numerically (handles `"$19.99"` vs `"19.99"`)
- Records with no extracted data are excluded from comparison
- Only fields listed in `monitor.tracked_fields` are compared

**Verify:**
- Two runs with different mock data produce correct field_changed, record_new, record_removed events.
- Non-monitor run_id produces no events (no-op path confirmed).
- `pytest tests -q` passes.

---

### Slice 6: Retention + Auto-Purge
**Status:** DONE
**Files:**
- `backend/app/services/monitor_retention.py` (new)
- `backend/app/tasks.py` (add Celery purge task — prod only, already stubbed in Slice 3)

**What:**

`MonitorRetentionService.purge_expired()`:
1. For each active monitor, delete `MonitorSnapshot` + `MonitorSnapshotRecord` rows where `created_at < now() - retention_days`
2. Delete `MonitorEvent` rows older than retention window
3. Delete orphaned `MonitorURLState` rows for archived monitors
4. Preserve `CrawlRun` and `CrawlRecord` rows (not monitor-specific data)
5. Log purge stats (monitor_id, rows deleted, duration)

Dev mode: `AsyncSchedulerLoop._maybe_purge()` calls this once every 24 hours (already wired in Slice 3).
Prod mode: Celery Beat task `monitor.purge_expired_snapshots` (already wired in Slice 3).

**Verify:**
- Snapshots older than `retention_days` are deleted after purge runs.
- `CrawlRun` rows are untouched.
- `pytest tests -q` passes.

---

### Slice 7: Frontend — Monitor Management UI
**Status:** DONE
**Files:**
- `frontend/app/monitors/page.tsx` (new)
- `frontend/app/monitors/[id]/page.tsx` (new)
- `frontend/components/monitors/monitor-config.tsx` (new)
- `frontend/components/monitors/monitor-history.tsx` (new)
- `frontend/components/monitors/monitor-events.tsx` (new)
- `frontend/lib/api/index.ts` (add monitor API calls including `runNow`)
- `frontend/lib/api/types.ts` (add monitor types)
- `frontend/components/layout/app-shell.tsx` (add nav link)

**What:**

Pages:
- `/monitors` — list all monitors with status badge, priority badge, last run time, next scheduled, change count since last visit
- `/monitors/[id]` — detail view:
  - Config summary (URLs, schedule, priority, tracked fields)
  - **Run Now button** → calls `POST /api/monitors/{id}/run/now`, shows returned run_id in toast
  - Recent events timeline (field_changed, record_new, record_removed)
  - History chart — tracked field values over time per URL (query `MonitorSnapshotRecord` directly by `monitor_id` + `source_url`)
  - Pause / resume / archive controls
  - Edit settings modal

Monitor creation form:
- URL input (multi-line or tag input)
- Surface selection
- Field selection (multi-select from `requested_fields` + defaults)
- Schedule interval picker (in hours)
- Priority selector (on_demand / priority / background)
- Retention days slider (1–90)

**Verify:** UI renders. Create / edit / pause monitor works end-to-end. Events display after a completed run. Run Now triggers a run and returns run_id.

---

### Slice 8: Programmatic Export API
**Status:** DONE
**Files:**
- `backend/app/api/monitors.py` (extend)

**What:**

Export endpoints:
- `GET /api/monitors/{id}/export/events.json` — all events within retention window
- `GET /api/monitors/{id}/export/events.csv` — CSV of change events
- `GET /api/monitors/{id}/export/snapshot.json` — current snapshot as structured JSON
- `GET /api/monitors/{id}/export/history.json` — time-series of tracked field values per URL (queried directly from `MonitorSnapshotRecord`)

**Verify:** All endpoints return correct data. CSV is well-formed. `pytest tests -q` passes.

---

## Dev vs Prod Runbook

### Dev Mode (default)
```bash
# .env
SCHEDULER_DRIVER=dev

# Start — no Celery, no Redis needed
uvicorn backend.app.main:app --reload
# Scheduler loop starts automatically via FastAPI lifespan
# Expected log: "AsyncSchedulerLoop started (interval=300s)"
```

### Prod Mode
```bash
# .env
SCHEDULER_DRIVER=celery

# Start stack
redis-server
celery -A app.core.celery_app worker --loglevel=info
celery -A app.core.celery_app beat --loglevel=info
uvicorn backend.app.main:app
# FastAPI lifespan detects SCHEDULER_DRIVER=celery — skips AsyncSchedulerLoop
```

---

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — add monitor bucket (models, services, API, frontend)
- [x] `docs/BUSINESS_LOGIC.md` — add monitor scheduling, priority tier contract, change detection decisions
- [x] `docs/backend-architecture.md` — add monitor subsystem; document dev vs prod scheduler
- [x] `docs/frontend-architecture.md` — add `/monitors` routes and components
- [x] `docs/INVARIANTS.md` — add:
  - Monitor scheduling contract: no silent schedule drift, retention always enforced
  - HEAD pre-check contract: on HEAD failure → proceed with full crawl, never skip silently
  - `core.py` hook contract: no monitor logic in pipeline body — one callback registration point only
  - On-demand runs must not affect `next_run_at`

## Notes

- `AsyncSchedulerLoop` is a dev harness only. Do not add retry logic, concurrency controls, or persistence to it. Those concerns live in `MonitorSchedulerService`.
- Monitor runs reuse the full existing pipeline — no special extraction path.
- Change detection is post-hoc (after run completes), not real-time.
- Multi-domain monitors create separate runs per domain to respect domain memory scoping.
- `notified_at` and `notification_status` on `MonitorEvent` now drive in-app notifications. Phase 2 can add webhook/email delivery without changing monitor extraction or scheduling paths.

# Plan: Product Monitoring Pipeline — Frontend Slices

**Created:** 2026-05-19
**Agent:** Codex
**Status:** DONE
**Scope:** Replaces Slice 7 in product-monitoring-pipeline-plan.md
---

## Do Not Touch

- Existing design tokens, CSS variables, and component primitives — extend only
- `frontend/components/ui/*` — use existing shadcn primitives as-is
- `frontend/lib/api/index.ts` existing exports — append only, no modifications
- Any existing crawl studio pages or components

---

## Slice 7a: API Layer + Types
**Status:** DONE
**Files:**
- `frontend/lib/api/types.ts` (extend — append monitor types)
- `frontend/lib/api/monitors.ts` (new — isolated monitor API module)
- `frontend/lib/api/index.ts` (extend — re-export monitors module)

**What:**

Add to `frontend/lib/api/types.ts`:
```typescript
export type MonitorPriority = "on_demand" | "priority" | "background";
export type MonitorStatus = "active" | "paused" | "archived";
export type MonitorEventType = "field_changed" | "record_new" | "record_removed";
export type NotificationStatus = "pending" | "sent" | "skipped";

export interface MonitorJob {
  id: string;
  name: string;
  urls: string[];
  domains: string[];
  surface: string;
  tracked_fields: string[];
  schedule_interval_hours: number;
  priority: MonitorPriority;
  retention_days: number;
  status: MonitorStatus;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonitorEvent {
  id: string;
  monitor_id: string;
  run_id: string | null;
  source_url: string;
  event_type: MonitorEventType;
  field_name: string | null;
  old_value: unknown;
  new_value: unknown;
  detected_at: string;
}

export interface MonitorSnapshotRecord {
  id: string;
  snapshot_id: string;
  monitor_id: string;
  source_url: string;
  url_identity_key: string;
  field_values: Record<string, unknown>;
  created_at: string;
}

export interface MonitorSnapshot {
  id: string;
  monitor_id: string;
  run_id: string;
  record_count: number;
  change_count: number;
  created_at: string;
}

export interface MonitorCreatePayload {
  name: string;
  urls: string[];
  surface: string;
  tracked_fields: string[];
  schedule_interval_hours: number;
  priority: MonitorPriority;
  retention_days: number;
  requested_fields: string[];
  settings?: Record<string, unknown>;
}

export interface MonitorUpdatePayload {
  name?: string;
  tracked_fields?: string[];
  schedule_interval_hours?: number;
  priority?: MonitorPriority;
  retention_days?: number;
  status?: MonitorStatus;
}

export interface RunNowResponse {
  run_id: string;
  dispatched_at: string;
  url_count: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
```

Create `frontend/lib/api/monitors.ts`:
```typescript
// All monitor API calls isolated here — do not scatter across components

export const monitorsApi = {
  list: (params?: { status?: MonitorStatus; priority?: MonitorPriority }) =>
    GET<MonitorJob[]>("/api/monitors", params),

  get: (id: string) =>
    GET<MonitorJob>(`/api/monitors/${id}`),

  create: (payload: MonitorCreatePayload) =>
    POST<MonitorJob>("/api/monitors", payload),

  update: (id: string, payload: MonitorUpdatePayload) =>
    PATCH<MonitorJob>(`/api/monitors/${id}`, payload),

  archive: (id: string) =>
    DELETE(`/api/monitors/${id}`),

  runNow: (id: string) =>
    POST<RunNowResponse>(`/api/monitors/${id}/run/now`),

  events: (id: string, params?: { page?: number; event_type?: MonitorEventType }) =>
    GET<PaginatedResponse<MonitorEvent>>(`/api/monitors/${id}/events`, params),

  history: (id: string, params?: { page?: number }) =>
    GET<PaginatedResponse<MonitorSnapshot>>(`/api/monitors/${id}/history`, params),

  currentSnapshot: (id: string) =>
    GET<MonitorSnapshotRecord[]>(`/api/monitors/${id}/snapshot/current`),
};
```

Use the same `GET` / `POST` / `PATCH` / `DELETE` fetch wrappers already in `frontend/lib/api/index.ts`.

**Verify:** All types importable. No TypeScript errors. `monitorsApi` functions callable with correct signatures.

---

## Slice 7b: Monitor List Page
**Status:** DONE
**Files:**
- `frontend/app/monitors/page.tsx` (new)
- `frontend/components/monitors/monitor-list-item.tsx` (new)
- `frontend/components/layout/app-shell.tsx` (extend — add Monitors nav link)

**What:**

`/monitors` page layout:
```
┌─────────────────────────────────────────────────────────┐
│  Monitors                              [+ New Monitor]  │
│  ─────────────────────────────────────────────────────  │
│  [All] [Active] [Paused] [Archived]    [Priority ▼]    │
│  ─────────────────────────────────────────────────────  │
│  ● belk-price-watch          active  · priority         │
│    12 URLs · every 2h · next in 47m · 3 changes today  │
│                                           [Run Now] [⋯] │
│  ─────────────────────────────────────────────────────  │
│  ● nordstrom-catalog         active  · background       │
│    50 URLs · every 6h · next in 2h  · 0 changes today  │
│                                           [Run Now] [⋯] │
└─────────────────────────────────────────────────────────┘
```

`MonitorListItem` component props:
```typescript
interface MonitorListItemProps {
  monitor: MonitorJob;
  onRunNow: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onArchive: (id: string) => void;
}
```

Status badge colors (use CSS variables from design system):
- `active` → sky blue accent
- `paused` → muted amber
- `archived` → muted gray

Priority badge:
- `on_demand` → solid accent
- `priority` → outline accent
- `background` → ghost / no border

`next_run_at` display: show as relative time ("next in 47m", "overdue") not ISO string.

Run Now on list page:
- Calls `monitorsApi.runNow(id)`
- Shows inline toast: `"Run dispatched · run_id: abc123"`
- Does not navigate away
- Button enters loading state during request, re-enables after response

Overflow menu (`⋯`): Pause / Resume / Archive — no destructive confirmation modal needed (soft delete only).

Nav link: Add "Monitors" to app-shell nav between existing items. Use a pulse indicator dot when any active monitor has `change_count > 0` since last visit (store last-visit timestamp in `localStorage`).

**Verify:** Page renders with empty state ("No monitors yet"). List renders with mock data. Run Now triggers API call. Status filter updates list. `pytest tests -q` passes (frontend build succeeds).

---

## Slice 7c: Monitor Creation Form
**Status:** DONE
**Files:**
- `frontend/app/monitors/new/page.tsx` (new)
- `frontend/components/monitors/monitor-form.tsx` (new — shared by create and edit)

**What:**

`MonitorForm` component — used for both create and edit (edit pre-populates values):

```typescript
interface MonitorFormProps {
  initial?: Partial<MonitorCreatePayload>;
  onSubmit: (payload: MonitorCreatePayload) => Promise<void>;
  onCancel: () => void;
  submitLabel: string;
}
```

Form fields:

**Name**
- Text input, required, max 100 chars

**URLs**
- Textarea — one URL per line
- Client-side validation: each line must match `^https?://`
- Show live count: "12 URLs" below textarea
- Warn (not block) if count exceeds 500

**Surface**
- Select dropdown — same surface options as existing crawl studio
- Reuse the surface option list from `frontend/lib/constants.ts` (do not hardcode)

**Tracked Fields**
- Multi-select checkboxes
- Default checked: `price`
- Available fields derived from surface selection (reuse field map already in codebase)
- If surface changes, reset tracked fields to default

**Schedule Interval**
- Number input + unit selector ("hours" / "days")
- Convert to hours internally before submit
- Min: 1 hour, display warning if < 1

**Priority**
- Segmented control: Background · Priority · On-Demand
- Tooltip on each option explaining dispatch behavior

**Retention**
- Slider: 1–90 days
- Show current value as label: "Keep 30 days of history"

**Settings (collapsible)**
- Collapsed by default, labelled "Advanced crawl settings"
- Exposes: proxy toggle, JS rendering toggle — same controls as crawl studio
- Do not rebuild these — extract and reuse from existing crawl config components

Submit behavior:
- Validate all required fields client-side before calling API
- On success: navigate to `/monitors/{id}`
- On error: show field-level error messages inline, do not navigate

**Verify:** Form submits valid payload. Validation blocks bad URLs. Surface change resets tracked fields. Navigation to detail page on success.

---

## Slice 7d: Monitor Detail Page
**Status:** DONE
**Files:**
- `frontend/app/monitors/[id]/page.tsx` (new)
- `frontend/components/monitors/monitor-header.tsx` (new)
- `frontend/components/monitors/monitor-events.tsx` (new)
- `frontend/components/monitors/monitor-history-chart.tsx` (new)
- `frontend/components/monitors/monitor-snapshot-table.tsx` (new)

**What:**

Page layout:
```
┌──────────────────────────────────────────────────────────────┐
│  ← Monitors   belk-price-watch          [Edit] [Run Now]    │
│               active · priority · every 2h                  │
│  ──────────────────────────────────────────────────────────  │
│  [Events]  [History]  [Current Snapshot]                    │
│  ──────────────────────────────────────────────────────────  │
│  (tab content)                                              │
└──────────────────────────────────────────────────────────────┘
```

#### `MonitorHeader` component

Displays: name, status badge, priority badge, schedule interval, last run (relative), next run (relative countdown), URL count, domain list (collapsed if > 3).

Controls:
- **Run Now** button — same behavior as list page (loading state, toast with run_id)
- **Edit** button — opens `MonitorForm` in a slide-over panel (not a new page)
- **Pause / Resume** — inline toggle button, updates status optimistically
- **Archive** — in overflow menu only, with confirmation ("Archive this monitor?")

#### Events Tab (`monitor-events.tsx`)

Paginated list of `MonitorEvent` rows, newest first.

Per-event row:
```
[field_changed]  price  ·  belk.com/product/123
                 $89.99  →  $74.99
                 2 hours ago
```

Event type display:
- `field_changed` → show field name + old → new value diff inline
- `record_new` → show URL + "New product detected"
- `record_removed` → show URL + "Product no longer found" (muted)

Filter bar: All · field_changed · record_new · record_removed

Empty state: "No changes detected yet. Run Now to trigger an immediate check."

#### History Tab (`monitor-history-chart.tsx`)

Line chart showing tracked field values over time per URL.

- X axis: snapshot `created_at` timestamps
- Y axis: field value (numeric for price; categorical for text fields)
- One line per URL (up to 10 URLs shown by default; "Show more" expands)
- URL selector: checkboxes to toggle individual URLs on/off
- Use `recharts` — already in the dependency list
- Data source: `GET /api/monitors/{id}/snapshot/current` for latest + `GET /api/monitors/{id}/history` for time series — do not build a bespoke endpoint; construct the series client-side from paginated history records

Empty state: "History will appear after the first completed run."

#### Current Snapshot Tab (`monitor-snapshot-table.tsx`)

Table of latest `MonitorSnapshotRecord` rows:

| URL | price | stock | last_changed |
|-----|-------|-------|-------------|
| belk.com/p/1 | $74.99 | in_stock | 2h ago |

Columns: `source_url` (truncated, links to URL), one column per tracked field, `last_changed_at` (relative).

Sortable by any column. Searchable by URL substring.

Empty state: "No snapshot yet. Run Now to capture the first data point."

#### Edit Slide-Over

Clicking Edit opens `MonitorForm` pre-populated in a `Sheet` (shadcn) sliding from the right. On save: closes sheet, re-fetches monitor detail, shows success toast. Does not navigate.

**Verify:** All three tabs render. Events paginate. History chart renders with mock data. Run Now updates header last_run_at after response. Edit slide-over saves and reflects changes without page reload.

---

## Slice 7e: Empty States + Loading States
**Status:** DONE
**Files:**
- `frontend/components/monitors/monitor-empty-state.tsx` (new)
- `frontend/components/monitors/monitor-skeleton.tsx` (new)

**What:**

Every data-fetching surface needs a skeleton and an empty state — Codex skips these by default. Define them explicitly:

`MonitorSkeleton` — used during initial page load:
- List page: 3 skeleton list item rows (pulsing, matches ListItem dimensions)
- Detail page: skeleton header block + skeleton tab content area

`MonitorEmptyState` — used when data is empty:
- List page empty: "No monitors yet. Create your first monitor to start tracking competitor prices." + [+ New Monitor] button
- Events tab empty: "No changes detected yet." + [Run Now] button
- History tab empty: "History will appear after the first completed run."
- Snapshot tab empty: "No snapshot yet." + [Run Now] button

Loading state on Run Now button:
- Button shows spinner + "Running…" text during request
- Disabled during in-flight request (prevent double-submit)
- On success: button re-enables, toast appears with run_id
- On error: button re-enables, inline error message below button

**Verify:** Skeleton renders on slow network (test with throttling). Empty states render when API returns empty arrays. Run Now button cannot be double-clicked during request.

---

## Slice Sequence

| # | Slice | Dependency |
|---|---|---|
| 7a | API Layer + Types | None — do this first |
| 7b | Monitor List Page | 7a |
| 7c | Monitor Creation Form | 7a |
| 7d | Monitor Detail Page | 7a, 7b, 7c |
| 7e | Empty + Loading States | 7d |

---

## Notes for Codex

- Do not create new fetch wrappers — use the existing ones in `frontend/lib/api/index.ts`.
- Do not create new design tokens — use existing CSS variables from the Obsidian Data Console system.
- Do not install new charting libraries — `recharts` is already available.
- Do not rebuild crawl config controls — extract and reuse from existing crawl studio components.
- `MonitorForm` is one component shared between create and edit — do not create separate form components for each.
- All relative time display ("2h ago", "next in 47m") must use a single shared utility — do not inline `Date` arithmetic in components.
- `next_run_at` countdown must not cause re-renders more than once per minute.
