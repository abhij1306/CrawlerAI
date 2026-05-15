These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Payload-budget checks can become inconsistent when the per-payload cap exceeds the total cap.
   Path: backend/app/services/acquisition/browser_capture.py
   Lines: 347-347

2. resource leak: Shutdown can stall because sentinel insertion depends on a bounded queue and an uncapped worker count.
   Path: backend/app/services/acquisition/browser_capture.py
   Lines: 98-98

3. possible bug: Non-mapping iterables can still trigger lossy merge handling.
   Path: backend/app/services/acquisition/browser_diagnostics.py
   Lines: 95-95

4. possible bug: Coercing the finalized status code to int can crash result assembly on non-numeric values.
   Path: backend/app/services/acquisition/browser_fetch_support.py
   Lines: 72-72

5. logic error: A missing success timestamp can cause the host to stay blocked when it should not.
   Path: backend/app/services/acquisition/host_protection_memory.py
   Lines: 125-125

6. possible bug: The new `proxy` parameter is accepted by `extract` but never used.
   Path: backend/app/services/adapters/amazon.py
   Lines: 175-175

7. logic error: The variant-order scoring logic can reject partially valid rows and change dimension ordering.
   Path: backend/app/services/adapters/amazon.py
   Lines: 509-509

8. type error: A non-list listing result can now be passed through into the adapter response and break callers expecting a list.
   Path: backend/app/services/adapters/base.py
   Lines: 318-318

9. logic error: The listing extractor can exceed its configured product limit before truncation.
   Path: backend/app/services/adapters/belk.py
   Lines: 63-63

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_fetch_support.py at line 74, The code is converting a None content_type into the string "None"; change the assignment that builds content_type from finalized (currently content_type=str(finalized.get("content_type", ""))) to treat an explicit None as an empty string by coalescing the fetched value (e.g., value = finalized.get("content_type"); if value is None use ""), then pass that safe string into content_type; update the place where content_type is constructed so finalized.get("content_type") never becomes the literal "None".

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/browser_fingerprint_profiles.py around lines 159 - 163, The code silently falls back to empty tuples when viewport_dims / line_width_range are not list/tuple; change this to log a warning and use sensible defaults: if viewport_dims is not a list/tuple, set it to (0, 0) and emit a warning mentioning "max_viewport_dims" and the received value; if line_width_range is not a list/tuple, set it to (1, 1) and emit a warning mentioning "aliased_line_width_range" and the received value; ensure these defaults are applied before any conversion to list later in this function so the WebGL profile format remains consistent (refer to the variables viewport_dims, line_width_range and limits["aliased_line_width_range"] in your changes).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/runtime_settings.py around lines 602 - 620, The accessors currently defensively cast to int and browser_capture_workers() is hardcoded; update the CrawlerRuntimeSettings dataclass to include browser_capture_workers: int = 4 (so it can be set via env/config), change browser_capture_workers() to return crawler_runtime_settings.browser_capture_workers, and remove unnecessary int() wrapping from browser_capture_max_network_payloads(), browser_capture_max_network_payload_bytes(), and browser_capture_total_network_payload_bytes() so they just return the already-validated integer fields; leave deprecation/removal of the legacy module-level constants for a follow-up.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/domain_run_profile_service.py at line 346, The expression building required_network_payloads uses int(str(diagnostics.get("network_payload_count") or 0)) which will raise ValueError if network_payload_count is a float (e.g., "5.7"); change the conversion to safely coerce numeric values by using int(diagnostics.get("network_payload_count") or 0) or explicitly cast via int(float(...)) so floats are truncated safely; update the assignment for required_network_payloads (and any related uses of diagnostics.get("network_payload_count")) to remove the intermediate str() and perform numeric conversion that tolerates ints and floats.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_dom_extractor.py at line 62, The import line redundantly aliases variant_option_availability to itself; update the import in detail_dom_extractor to remove the unnecessary alias by importing variant_option_availability directly (replace any occurrence of "variant_option_availability as variant_option_availability" with just "variant_option_availability" in the import statement).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_integrity_gate.py around lines 251 - 259, The function _ensure_frozenset treats dicts as generic Iterables which will iterate keys (possibly unintended); update _ensure_frozenset to explicitly detect dict instances (e.g., via isinstance(value, dict)) and convert them to a frozenset of their values or key-value pairs as required by your domain (for example frozenset(str(v) for v in value.values()) if you expect dict-of-values), otherwise fall back to the existing Iterable handling; keep the existing branches for frozenset, str and general Iterable and ensure the return type remains frozenset[str].