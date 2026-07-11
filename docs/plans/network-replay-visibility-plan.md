# Plan: Network Replay Visibility

**Created:** 2026-07-10
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 2 (orchestration), 3 (acquisition), 6 (domain memory), frontend

## Goal

Make internal-API replay observable in Crawl Studio. Operators can see whether an
endpoint was learned, used, rejected, or evicted without exposing response bodies or
POST request payloads.

## Acceptance Criteria

- [x] Real captured PDP APIs with endpoint-bound product IDs were audited; non-PDP
  promo/review/analytics payloads remain rejected and report their reason in Logs.
- [x] Run Logs show replay use, fallback, learning, and eviction as acquisition events.
- [x] Domain Memory displays endpoint method, route, status, and failure count without request JSON.
- [x] Frontend API schemas preserve safe replay metadata and exclude endpoint URLs.
- [x] Focused backend pytest and VitePlus frontend tests pass.

## Do Not Touch

- `app/extraction/*` — replay visibility must not affect extraction.
- `app/publish/*` — this is acquisition/profile observability.
- Network payload bodies and POST request JSON — never display or log them.

## Slices

### Slice 0: Endpoint-bound same-product admission
**Status:** DONE
**Files:** `app/acquisition/internal_api_replay.py`, focused backend tests
**What:** Audit captured run 34 exchanges. The endpoint-bound requests were product
recommendations, reviews, availability, promotions, or analytics rather than a PDP
document, so admitting them would violate same-product/complete-record policy. Keep
the gate strict and log zero-candidate/rejected-candidate reasons.
**Verify:** focused backend tests pass; run 34 artifact audit confirms zero valid PDP APIs.

### Slice 1: Safe replay diagnostics and log events
**Status:** DONE
**Files:** `app/acquisition/*`, `app/crawl/pipeline/*`, focused backend tests
**What:** Add stable, URL-safe replay event data and emit acquisition logs for use,
fallback, learning, and eviction.
**Verify:** focused backend pytest exits 0.

### Slice 2: Domain-profile API projection
**Status:** DONE
**Files:** `app/schemas/crawl.py`, focused backend tests
**What:** Expose route and failure metadata, never `request_json`.
**Verify:** schema/API test exits 0.

### Slice 3: Crawl Logs and Domain Memory UI
**Status:** DONE
**Files:** `frontend/lib/api/*`, `frontend/components/crawl/*`,
`frontend/components/selectors/domain-memory/*`, focused frontend tests
**What:** Render replay status in logs and a read-only endpoint panel in Domain Memory.
**Verify:** focused `vp test` and `vp check --fix` exit 0.

## Doc Updates Required

- [x] `docs/BUSINESS_LOGIC.md` — operator visibility behavior.
- [x] `docs/frontend-architecture.md` — Domain Memory panel ownership.
- [x] `docs/CODEBASE_MAP.md` — no production file added or moved.

## Notes

Opened after the Phase 5 backend implementation. Response bodies and sanitized POST
templates remain backend-only; UI shows only safe endpoint metadata.

Completed 2026-07-10. Run 34 had 90 captured browser JSON exchanges but no valid
public PDP replay document. Logs now distinguish zero same-product candidates from
anonymous-verification rejection. `ruff check .`, 64 focused backend component tests,
`vp test app/domain-memory/page-view.test.tsx` (7 tests), and `vp check --fix` pass.
