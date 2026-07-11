# Plan: Phase 5 Network Replay Fixes (G1-G7)

**Created:** 2026-07-10
**Agent:** GLM 5.2; audited and completed by Codex
**Status:** DONE
**Touches buckets:** 3 (Acquisition), 2 (Crawl Profile/Orchestration), 4 (Extraction), 6 (Config)

## Goal

Fix the replay gaps without templating or rewriting endpoint URLs. Done means replay
stores bounded, exact-route endpoint memory; validates anonymous public access; rejects
wrong-page payloads; evicts dead endpoints; and proves empty-HTML replay extraction.

## Acceptance Criteria

- [x] G6: POST replay payload carries `request_json` so a successful replay re-learns POST endpoints
- [x] G2: `api.*` subdomains learnable and www/apex matching is consistent
- [x] G3: significant route query keys and a listing source-route payload gate prevent wrong-page replay
- [x] G7: anonymous verification replay runs before browser-captured endpoints persist
- [x] G4: per-endpoint failure count evicts endpoints after the configured consecutive-failure threshold
- [x] G1: bounded exact-route endpoint memory serves multiple learned routes without URL templating
- [x] G5/T2: detail and job-listing component tests extract from empty-HTML `api_replay` bundles
- [x] focused replay-gate, wrong-page, POST re-learn, persistence, eviction, and extraction tests pass
- [x] focused `ruff check` passes

## Do Not Touch

- `app/publish/*` — fix upstream, not downstream (INVARIANTS Rule 3)
- `app/pipeline/persistence.py` — extraction-owned repair only
- Browser challenge/identity subsystem — out of scope for replay

## Slices

### Slice 1: G6 — Carry `request_json` through replay payload
**Status:** DONE
**Files:** `app/acquisition/internal_api_replay.py`
**What:** `_replay_endpoint` return dict includes `request_json` (when present) so
`learned_internal_api_endpoints` re-derives POST endpoints from replay success.
**Verify:** `pytest tests/component/test_acquirer.py -q` + new T5 covers relearn.

### Slice 2: G2 — Host asymmetry fix
**Status:** DONE
**Files:** `app/acquisition/internal_api_replay.py`, `app/core/config/domain_profiles.py`
**What:** (a) Allow first-party subdomains (`api.`, `shop.`) when the page domain is
the apex/www. Add an allow-listed first-party-subdomain set to config.
(b) Make learn-time `_endpoint_from_payload` and replay-time `_is_safe_replay_url`
use the same comparison (registered-domain equality, not exact hostname).
**Verify:** T1 gate matrix + focused test.

### Slice 3: G3 — Route identity + listing safeguard
**Status:** DONE
**Files:** `app/acquisition/internal_api_replay.py`, `app/core/config/domain_profiles.py`
**What:** (a) `_route_identity` retains significant query params (page/variant) so
`/jobs?page=2` ≠ `/jobs?page=1`. (b) Add a listing wrong-page check: the response
must name the requested listing route (page param overlap), not just any same-domain row.
**Verify:** T4 test.

### Slice 4: G7 — Verify-at-learn (anonymous provenance)
**Status:** DONE
**Files:** `app/crawl/profile/acquisition_contract.py`, `app/acquisition/internal_api_replay.py`
**What:** Before persisting a learned endpoint, run the same replay code path
anonymously; only store endpoints proven to return a usable response.
Neutralizes half of G2/G4 at learn time.
**Verify:** focused test in `test_crawl_service.py`.

### Slice 5: G4 — Endpoint failure counter + eviction
**Status:** DONE
**Files:** `app/core/config/domain_profiles.py`, `app/crawl/profile/normalization.py`, `app/acquisition/internal_api_replay.py`
**What:** Add per-endpoint `failure_count` to the normalized endpoint. On replay
failure (non-2xx, gate fail), increment; after N consecutive failures drop the
endpoint from the profile. Config threshold in `domain_profiles.py`.
**Verify:** T6-style focused test.

### Slice 6: G1 — Exact-route endpoint memory
**Status:** DONE
**Files:** `app/acquisition/internal_api_replay.py`, `app/crawl/profile/normalization.py`, `app/core/config/domain_profiles.py`
**What:** Audit rejected route templating: it would infer endpoint URLs without
same-product evidence. Accumulate bounded exact-route endpoints instead, keyed by
method, URL, route, and POST template.
**Verify:** focused test keeps two distinct routes.

### Slice 7: T1 — Gate matrix unit tests
**Status:** DONE
**Files:** `backend/tests/component/test_acquirer.py`
**What:** http downgrade, cross-domain, `api.` subdomain, www/apex asymmetry
round-trip, blocked paths, POST without request_json, 3xx response, oversized body.
**Verify:** `pytest tests/component/test_acquirer.py -q`.

### Slice 8: T2 / G5 — Extraction from api_replay bundle
**Status:** DONE
**Files:** `backend/tests/component/test_internal_api_replay_extraction.py` (new)
**What:** Build `PageAcquisitionResult(method="api_replay", html="", network_payloads=[...])`
for ecommerce_detail and job_listing; run `extract_records_for_acquisition_result`
real and assert records are sourced from network evidence.
**Verify:** new test exits 0.

### Slice 9: T4 — Wrong-page listing replay
**Status:** DONE
**Files:** `backend/tests/component/test_acquirer.py`
**What:** Learn on `/jobs?page=1`, request `/jobs?page=2`; assert replay refused
or rows match page 2.
**Verify:** focused test.

### Slice 10: T5 — Loop sustainability
**Status:** DONE
**Files:** `backend/tests/component/test_crawl_service.py`
**What:** After successful api_replay run, profile still contains the endpoint
(and `request_json` for POST — covers G6).
**Verify:** focused test.

## Doc Updates Required

- [x] `docs/INVARIANTS.md` — replay endpoint-memory and eviction contract
- [x] `docs/CODEBASE_MAP.md` — no production files added or moved
- [x] `docs/backend-architecture.md` — acquisition replay behavior
- [x] `docs/plans/phase5-network-replay-review-2026-07-10.md` — each G annotated

## Notes

Started 2026-07-10. Codex audit changed G1 from endpoint templating to bounded
exact-route memory: templating would publish an inferred endpoint URL without
same-product evidence. Verified 2026-07-10: focused ruff passes; 65 focused
component tests pass.
