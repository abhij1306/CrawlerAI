# Plan: Latest Commerce Artifact Integrity

**Created:** 2026-06-27
**Agent:** Codex
**Status:** DONE
**Touches buckets:** acquisition diagnostics, extraction collectors, entity resolution, validation, materialization, replay harness, extraction architecture docs

## Goal

Replay the latest named commerce artifacts, prove each failure from captured HTML/network evidence, and fix the upstream owner for each defect. Done means sparse shell pages are not accepted as successful detail records, unrelated network payloads cannot become product variants, product fields are resolved only from same-product evidence, and every unresolved field has an honest source-capability or extraction diagnostic. No site-specific hacks, no downstream export repair, no smoke commands.

## Acceptance Criteria

- [x] B&H Cozyla, Ralph Lauren, Lululemon, and Valentino sparse shell artifacts do not produce public title/url-only success records.
- [x] Brooklinen towels do not include the `Wool/Cotton` ad/feed row and never publish duplicate `variant_id` values.
- [x] Dime description preserves word/list boundaries and does not concatenate product title plus feature text.
- [x] Jordan and HOKA image decisions are product-scoped and do not select sibling/incorrect-color assets when same-product evidence exists.
- [x] Peter Do extensionless CDN images are classified from asset evidence, not rejected or accepted by file suffix alone.
- [x] Nike, HOKA, Apple, Breville, and Adidas variant outcomes distinguish sellable variants, option inventories, source absence, and interaction gaps.
- [x] Aesop, Rolex, Jordan, HOKA, J.Crew, and 47 brand outcomes reject structural/retailer pollution and keep evidence-backed product brands.
- [x] Phase Eight, Farfetch, Gucci, ELEUTERI, Cartier, and Decathlon price/currency outcomes are recovered from valid offer evidence or diagnosed as unavailable/rejected with lineage.
- [x] Puma Spanish/ARS output is treated as source-faithful unless a separate localization feature is requested.
- [x] Targeted tests pass after each slice; final repo-level verification passes without smoke commands.

## Do Not Touch

- `backend/app/publish/*` — downstream publishing must not repair extraction semantics.
- `backend/app/crawl/pipeline/*` — persistence/export must not compensate for bad extracted fields.
- `backend/app/connectors/llm/*` — LLM remains opt-in adjudication/backfill only.
- Site-specific adapter branches or hostname exception lists — fixes must be generic.
- Unrelated frontend startup changes — preserve unless needed for requested verification.

## Slices

### Slice 1: Latest Artifact Replay Manifest
**Status:** DONE
**Files:** replay harness/tests and compact artifact case manifest
**What:** Add focused replay cases for every named artifact. Assertions must inspect generated output, findings, field states, public variant ids, image lineage, and sparse-record verdicts.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests\unit\test_latest_commerce_artifact_integrity.py -q`

### Slice 2: Sparse Shell Acquisition Truth
**Status:** DONE
**Files:** `backend/app/acquisition/*`, acquisition contracts/result diagnostics, extraction verdict glue
**What:** Classify HTTP error bodies, challenge pages, PX/captcha shells, redirect-only shells, and low-content JSON as source-unavailable detail acquisitions. Prevent URL-derived title/url-only public success records when product sources are unavailable.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests\unit\test_source_capabilities.py tests\unit\test_extraction_pipeline.py -q -k "source_capabilit or shell"`

### Slice 3: Network Root Admission And Variant Identity
**Status:** DONE
**Files:** `backend/app/extraction/collectors/metadata.py`, `backend/app/extraction/collectors/js_state.py`, `backend/app/extraction/entities.py`, `backend/app/extraction/validation.py`, `backend/app/extraction/materialization.py`
**What:** Reject ad/feed/analytics/recommendation network roots unless strongly related to the selected product. Keep `variant_id`, `variant_sku`, product ids, and structural ids distinct. Block duplicate public variant ids before success.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests\unit\test_latest_commerce_artifact_integrity.py tests\unit\test_extraction_pipeline.py -q -k "variant or network or identity"`

### Slice 4: Variant And Offer Evidence States
**Status:** DONE
**Files:** variant collectors, offer collectors, resolver, validation
**What:** Split option inventory from sellable variants. Split absent price from captured-but-rejected price and source-unavailable price. Do not synthesize variants or prices.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests\unit\test_latest_commerce_artifact_integrity.py tests\unit\test_extraction_pipeline.py tests\unit\test_variant_offer_availability_semantics.py -q -k "variant or offer or price or field_state"`

### Slice 5: Brand, Asset, And Text Fidelity
**Status:** DONE
**Files:** scalar coercion, brand resolver, asset resolver, DOM text collector, document decode path
**What:** Reject numeric/structural brands, demote retailer brands, preserve description boundaries, rank only same-product assets, and classify opaque image URLs by evidence.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q -k "brand or asset or description or text"`

### Slice 6: Docs And Final Quality Gates
**Status:** DONE
**Files:** `docs/INVARIANTS.md`, `docs/backend-architecture.md`, `docs/ENGINEERING_STRATEGY.md`, plan docs
**What:** Update canonical docs for changed contracts, run full ruff, mypy, pylint, and pytest without smoke commands, then mark this plan done.
**Verify:** `.\.venv\Scripts\python.exe -m ruff check .`; `.\.venv\Scripts\python.exe -m mypy .`; `.\.venv\Scripts\python.exe -m pylint app`; `.\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — artifact replay gate and field-state ownership.
- [x] `docs/INVARIANTS.md` — sparse shell/public record and duplicate public variant-id contracts.
- [x] `docs/ENGINEERING_STRATEGY.md` — network payload pollution anti-pattern if new guard is added.

## Notes

- User forbids smoke commands. Use targeted pytest during slices. Run repo-level pytest only at end.
- Puma localization is not an extraction defect under current source-faithful contract.
- Existing staged frontend startup changes predate this implementation and must be preserved.
- 2026-06-27: Latest artifact replay gate added and passing for Dime, Brooklinen, Lululemon, B&H, Valentino, Rolex, Aesop, and Jordan. Targeted owner tests passed: `107 passed, 129 deselected` for source capability, brand, description, variant/shell subsets. Latest gate passed: `3 passed`.
- 2026-06-27: Slice 4 frozen and verified. Latest manifest now covers Nike, Apple, Breville, Adidas, Phase Eight, Farfetch, Gucci, Net-a-Porter, Mr Porter, and Decathlon variant/offer states. Targeted verify passed: `85 passed, 147 deselected`.
- 2026-06-27: Slice 5 frozen and verified. Targeted asset/brand/text gate passed: `53 passed, 170 deselected`.
- 2026-06-28: Final artifact audit replayed all 24 named cases from stored HTML/network evidence. Result: `quality_clean=True`, zero integrity failures, zero field-state mismatches, zero invariant failures, and zero unresolved issue ids. Coverage includes Ralph Lauren, 47, J.Crew, and Puma source-locale cases.
- 2026-06-28: Root-cause follow-up fixed retailer-host brand evidence outranking a path/title manufacturer candidate, apostrophe-prefixed numeric brands being rejected, and `srcset` parsing that split CDN URLs at embedded transformation commas and created false relative image URLs.
- 2026-06-28: Final gates passed: Ruff clean; mypy clean across 342 source files; pylint `10.00/10`; full pytest with normally unselected tests enabled: `1271 passed, 6 skipped`. No smoke commands were run.
