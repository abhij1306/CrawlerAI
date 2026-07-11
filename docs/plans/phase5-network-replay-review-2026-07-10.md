# Phase 5 Review — Internal API Replay (network-first acquisition)

Date: 2026-07-10
Scope: the Phase 5 architecture that learns internal API endpoints from a successful
browser capture and replays them HTTP-only on future runs so the browser render is
skipped. Reviewed against the actual code, not the plan doc. The user has not tested
this path end-to-end yet; Part 4 is the test plan for that.

---

## Part 1 — What exists (the loop, as implemented)

The loop closes. Every stage is wired:

```
run N (browser)                                run N+1 (HTTP-only)
───────────────                                ────────────────────
browser capture                                build_acquisition_request
  └─ network_payloads (capped, sanitized)        └─ resolve_url_acquisition_recipe
extraction succeeds (quality success)                └─ load_domain_run_profile
  └─ record_acquisition_contract_outcome            └─ merge_saved_run_profile
       └─ learned_internal_api_endpoints              (endpoints merged by (method,url))
       └─ save_domain_run_profile              AcquisitionPolicy.from_profile
            [INTERNAL_API_ENDPOINTS_PROFILE_KEY]  └─ policy.to_profile() → request
                                               acquire()
                                                 └─ replay tried BEFORE fetch_page
                                                     (unless fetch_mode == browser_only)
                                                 └─ success → method="api_replay",
                                                     html="", network_payloads=[payload],
                                                     extraction_source="network_payload_first"
                                               extraction (network_json collectors)
                                                 └─ quality success → re-records contract,
                                                     re-learns endpoint from replay payload
                                                     (loop sustains itself)
```

| Stage | Where | Status |
|---|---|---|
| Capture: payload admission, byte/count caps | `acquisition/browser_capture.py` (`_should_capture_payload`, `_reserve_capture_budget`) | Implemented |
| Capture: POST template sanitization | `browser_capture.py::_safe_replay_request_json` — JSON only, GraphQL mutations rejected, sensitive-key recursion, size cap, allow-listed headers only | Implemented |
| Learn: endpoint derivation on quality success | `crawl/profile/acquisition_contract.py:277` → `internal_api_replay.py::learned_internal_api_endpoints` | Implemented |
| Persist: domain run profile | `save_domain_run_profile` under `internal_api_endpoints` key; normalized by `crawl/profile/normalization.py::normalize_internal_api_endpoints` | Implemented |
| Load: profile → request | `retry/stage.py::build_acquisition_request` → `resolve_url_acquisition_recipe` → `merge_saved_run_profile` (merge.py:192-214, keyed by (method,url), explicit wins) → `CrawlRunSettings.acquisition_profile()` → `AcquisitionPolicy.from_profile` | Implemented |
| Replay: HTTP-only attempt before fetch | `acquisition/acquirer.py:242-252` (`_acquire_from_internal_api_replay`) | Implemented |
| Extract: replay bundle | `extraction/replay.py::request_from_acquisition_result` — payload becomes a `network_json` artifact; detail `NetworkCollector` (collectors/metadata.py:84) and listing `collect_network_listing` (network_listing.py:44) both read that artifact type | Implemented (but see G5) |
| Re-record: sustain the loop | `record_extraction_stage.py:386` passes `network_payloads` (which on replay is the replay payload itself) back into contract memory | Implemented |
| Kill switch / knobs | `internal_api_replay_enabled=True`, `timeout=3.0s`, `max_endpoints=3` (`runtime_settings.py:222-224`) | Implemented |

Host pacing is preserved: `PolicyMiddleware.before_fetch` (rate limiter) runs before
the replay attempt, and `after_fetch` records the outcome, so replay does not bypass
per-host politeness.

## Part 2 — Verified safety properties (all confirmed in code)

1. **HTTPS-only, same registered domain, same exact origin** — `_is_safe_replay_url`
   (internal_api_replay.py:213). Also `validate_public_target` (SSRF guard: replayed
   even though the endpoint was validated at learn time — good, DNS can change).
2. **No redirects followed** (`follow_redirects=False`, 3xx rejected), **byte cap**
   streamed (`browser_capture_max_network_payload_bytes`), **3s timeout**.
3. **Route identity gate** — `source_route` stored at learn time must equal
   `_route_identity(page_url)` at replay time (:112-115). Endpoint memory is
   domain-wide, replay eligibility is per-route.
4. **Product A/B safeguard** — for detail surfaces `_record_url_matches_page` (:365)
   requires the response body to contain a URL identifying the requested route before
   the payload is accepted. A stale response for product A cannot publish as product B.
5. **POST restricted** to `graphql|job_api|product_api` with a captured, sanitized
   `request_json`; GraphQL mutations and sensitive-key payloads are never captured in
   the first place (`_safe_replay_request_json`).
6. **Content gate both directions** — `payload_extracts_surface` runs at learn time
   AND at replay time; junk responses fall through to normal acquisition.
7. **Blocked-path markers** (`INTERNAL_API_REPLAY_BLOCKED_PATH_MARKERS`) checked at
   learn and replay.
8. **Failure is always graceful** — any gate failure or HTTP error returns `None` and
   `acquire()` proceeds to the normal fetch cascade. `browser_only` retries bypass
   replay entirely (acquirer.py:242), so the escalation ladder cannot loop back into
   a broken replay.

## Part 3 — Gaps and risks (ranked)

### G1 (architectural, FIXED 2026-07-10) — endpoint memory is last-writer-wins per (domain, surface); replay only ever serves the most recently succeeded route
`record_acquisition_contract_outcome` overwrites `internal_api_endpoints` with the
endpoints of the page that just succeeded (acquisition_contract.py:285). All learned
endpoints carry that one page's `source_route`, and replay requires
`source_route == _route_identity(page_url)`. Net effect: after crawling 100 product
pages, the profile holds endpoints for the *last* one only, and on the next run 99 of
100 URLs go straight back to the browser. The saved-profile merge in merge.py keys by
`(method, url)` — but since endpoint URLs are page-specific
(`/api/products/replay-widget.json`), old entries are replaced, not accumulated, and
even accumulation would be capped at `max_endpoints=3` by
`normalize_internal_api_endpoints`.
**This is the main reason the feature will look like it "doesn't work" in testing at
any scale.** The design goal ("avoid browser renders in future runs") needs either:
(a) a URL-templated endpoint (learn `/api/products/{slug}.json` as a pattern keyed by
route shape, the way `record_bindings.v1` recipes generalize), or (b) per-route
endpoint storage rather than one list per domain+surface.

### G2 (silent no-op, FIXED 2026-07-10) — host asymmetries make endpoints unlearnable or unreplayable
Two related, verified issues:
- **`api.*` subdomains are never learned.** `_endpoint_from_payload` (:250) requires
  `normalize_domain(endpoint) == normalize_domain(page)`, and `normalize_domain` only
  strips `www.` — verified: `api.example.com ≠ example.com`. A very common real-world
  shape (page on `www.`, JSON on `api.`) silently learns nothing.
- **www/apex mismatch learns but never replays.** Learn-time uses `normalize_domain`
  (www-insensitive) but replay-time `_is_safe_replay_url` also requires exact
  `_origin` hostname equality. An endpoint on `example.com` learned from a
  `www.example.com` page passes learning and fails replay forever — wasted profile
  entries and a confusing "endpoints exist but replay never fires" symptom.
At minimum make the two checks consistent; better, allow an explicit allow-list of
first-party subdomains captured as evidence (the endpoint was literally observed
serving this page's data — that provenance is the trust anchor).

### G3 (correctness, FIXED 2026-07-10) — `_route_identity` strips query strings; listing has no wrong-page safeguard
Verified: `/jobs?page=1` and `/jobs?page=2` have identical route identity, as do
`?variant=blue|red` detail URLs. For detail, `_record_url_matches_page` mitigates
(the body must name the route — but it too compares query-stripped identities, so a
variant-B response can still publish for variant-A URLs). For **listing there is no
equivalent gate at all**: `_payload_has_listing_row` only checks that *some*
same-domain row exists, so page-2 of a paginated listing will replay the endpoint
learned on page-1 and publish page-1's rows as page-2's content. Fix: keep the query
string in `source_route` (or hash significant params), and for listings require some
overlap check or store the full learned URL including query.

### G4 (performance/hygiene, FIXED 2026-07-10) — no eviction or negative feedback for dead endpoints
A learned endpoint that starts failing (401 after session change, API version bump,
CDN rule) is retried on **every** acquisition: up to 3 endpoints × 3s sequential
before falling through to fetch. Nothing decrements or removes it — the
`stale_after_failures` counter applies to the acquisition contract, and even a stale
contract does not gate replay (`apply_acquisition_contract_to_profile` only annotates;
endpoints flow into the request regardless). Add a per-endpoint failure counter in the
profile and drop endpoints after N consecutive replay failures.

### G5 (test gap, CLOSED 2026-07-10) — nothing proves an `html=""` api_replay bundle survives extraction end-to-end
The replay result carries `html=""`; the only evidence source is the single
`network_json` artifact. Detail's `NetworkCollector` and listing's
`collect_network_listing` do read it, but downstream gates were designed against real
pages: the ECOMMERCE_DETAIL `_normalized_detail_outcome` shell/not-found
classification, entity binding, and validation gates have never been exercised with an
empty DOM. Every existing test mocks `replay_internal_api_endpoints` or stops at the
acquisition boundary — **no test extracts records from an api_replay
`PageAcquisitionResult`**. If any gate demands DOM corroboration the whole feature
succeeds at acquisition and dies at extraction with `insufficient_input_bundle`,
which the retry ladder then converts back into a browser run (safe, but the feature
silently never pays off). This is the first thing to test (T2 below).

### G6 (minor, FIXED 2026-07-10) — POST endpoints degrade after their first successful replay
The replay payload (`_replay_endpoint`'s return) does not include `request_json`, so
when a replay success re-learns endpoints from its own payload, `_endpoint_from_payload`
rejects the POST re-derivation (requires `request_json`). Saving is skipped when the
learned list is empty (`if endpoints:`), which protects the stored copy in the pure
case — but a mixed GET+POST profile will be overwritten with the GET-only list.
Carry `request_json` through into the replay payload dict.

### G7 (by design, FIXED 2026-07-10) — only truly public endpoints can ever replay
Capture strips cookies/auth headers (allow-listed headers only) and replay sends a
bare request from the shared client. Endpoints requiring session cookies, CSRF tokens,
or API keys will always fail replay. That is the right security posture, but it means
learn-time success does not imply replay-time success. A cheap improvement: do one
**verification replay at learn time** (same code path, before persisting) so the
profile only ever stores endpoints proven to work anonymously. This also neutralizes
half of G2 and G4.

## Part 4 — Test plan (feature is untested; ordered by information value)

**T1 — unit: gate matrix for `_is_safe_replay_url` / `_endpoint_from_payload`.**
Cases: http downgrade, cross-domain, `api.` subdomain (documents G2 as expected-fail
or drives the fix), www/apex asymmetry (learn-then-replay round trip — currently
fails), blocked paths, POST without request_json, 3xx response, oversized body.

**T2 — component: extraction from an api_replay bundle (closes G5).**
Build a `PageAcquisitionResult(method="api_replay", html="", network_payloads=[...])`
for (a) ecommerce_detail and (b) a job listing payload; run
`extract_records_for_acquisition_result` for real (no mocks) and assert verdict is
publishable with records sourced from `network_payload`. This is the single most
important missing test.

**T3 — integration: two-run loop against a fixture site.**
Run 1 with browser capture on a fixture serving a product page + JSON endpoint;
assert profile contains the endpoint. Run 2 same URL; assert `method == "api_replay"`,
no browser launch, and record parity with run 1. Then mutate the fixture endpoint to
return 500 and assert run 3 falls through to normal fetch and still publishes.

**T4 — regression: wrong-page listing replay (documents G3).**
Learn on `/jobs?page=1`, request `/jobs?page=2`, assert replay is either refused or
the published rows match page 2 — currently this test will fail and is the
reproduction for the G3 fix.

**T5 — loop sustainability.** After a successful api_replay run, assert the profile
still contains the endpoint (and `request_json` for POST — currently fails, G6).

**T6 — eviction (after G4 fix).** Endpoint failing N times is removed and acquisition
latency returns to baseline.

Existing coverage for reference: 6 replay tests in
`tests/component/test_acquirer.py` (ordering, browser_only bypass, SSRF/https gates,
title-only rejection, wrong-detail rejection) + 1 learn-persistence test in
`test_crawl_service.py`. All good, none cover extraction or multi-run behavior.

## Verdict

The Phase 5 loop is genuinely implemented end-to-end and the safety engineering is
strong (SSRF, origin, redirect, mutation, sensitive-key, product A/B gates all real).
What is missing is *effectiveness*, not safety: G1 limits replay to one URL per
domain+surface (so the browser-avoidance win is near-zero at scale), G2 silently
excludes the most common API-host shapes, and G5 means the payoff path — extracting
from an empty-HTML replay bundle — has never been executed. Recommend running T2 and
T3 before any tuning, then fixing G1 (endpoint templating / per-route storage) as the
first architecture change, since it determines whether Phase 5 is a cache or a
capability.
