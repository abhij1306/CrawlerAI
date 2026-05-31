# Plan: Per-Variant Availability from Rendered DOM (Nike, Belk, generic)

Status: IN PROGRESS (not verified, not done). Core DOM-signal fix landed + full suite green.
Reconciliation layer drafted but NOT wired and NOT correct yet. Treat as untrusted until verified.

---

## Problem (user report)

- Nike PDP: variant `availability` missing; sizes incomplete. Out-of-stock sizes are
  simply absent from output, and no per-variant availability.
- Belk PDP: per-variant `availability` missing; all out-of-stock variants are missed.
- User framing (correct): this is an architectural gap affecting MOST sites, not a
  Nike/Belk-specific bug. Per-variant availability is generally not extracted.

Canonical size format the user expects for Nike is the rendered label, e.g. `M 5 / W 6.5`
(NOT the short JSON-LD token `5`).

---

## Root cause (confirmed with real artifacts)

Per-variant availability had ONE DOM owner: `variant_option_availability` in
`backend/app/services/extract/detail/variants/dom_options.py`. It only read class
tokens (`outstock`, `soldout`, `unavailable`) and visible text (`out of stock`,
`sold out`, `N left`). It NEVER read the universal machine-readable OOS signal:
a `disabled` / `aria-disabled` control or `data-disabled` / `data-available=false`
/ `data-oos` flag. `grep disabled` across all of `extract/` returned ZERO hits.

Constraint (existing passing regression contract): a `disabled` control that is ALSO
the currently-selected option must NOT be treated OOS (a selected swatch is often
disabled to lock it in). See
`test_variant_option_availability_does_not_treat_disabled_control_as_out_of_stock`.

Cross-tier reality verified from stored artifacts:
- Real Nike artifact: `artifacts/runs/6/pages/1bcb5c849a75b86f.html` (also run 7). Uses
  `__NEXT_DATA__`. ALL 22 sizes report `status: ACTIVE`; real stock is fetched
  client-side later (`isSkusRequestInFlight`, empty `selectedSku`). In the FULL pipeline
  the winning record is `_source: json_ld`, and Nike's JSON-LD lists only the 19 IN-STOCK
  sizes (omits the 3 OOS: `5`, `5.5`, `16`). The rendered DOM has all 22 as
  `<input id="grid-selector-input-{size}" value="{size}">` + `<label>M X / W Y</label>`,
  where OOS ones carry `disabled` (5, 5.5) or `aria-disabled` (16).
- Real Belk artifacts: `artifacts/runs/5/pages/{1e522030794b8b5e,1f753ed82e93ff47,95e1e04e3ba1f49d}.html`.
  Radix UI `<button role="radio" aria-checked data-state data-disabled disabled value="10512_33x32">`
  size buttons; OOS ones carry `disabled` + `data-disabled=""`. `sku_out_of_stock`/
  `sku_inventory` arrays exist but are RSC-streamed (not simple inline JSON). Real Belk
  URLs (from trace.json):
  - `https://www.belk.com/p/izod-swingflex-pants/3203960IZAGC08R.html?dwvar_3203960IZAGC08R_color=020428016978`
  - `https://www.belk.com/p/nautica-classic-flat-front-deck-pants/3201634P81106.html?dwvar_3201634P81106_color=156300395171`

Therefore: the structured/adapter tier reports everything available (or omits OOS rows),
and the rendered DOM is the only source of truth for per-variant stock. The fix must read
the DOM disabled/flag signal AND reconcile it onto the winning record's variant rows,
including appending OOS variants the structured tier dropped.

### Important pipeline facts discovered (save future time)
- `extract_records` import path: `app.services.pipeline.extract_records` (NOT
  `app.services.crawl_engine`).
- Default `pytest.ini` `addopts` filter is `-m "unit or component"`. Regression tests are
  deselected unless you pass `-m regression`.
- `variants` is in BOTH `STRUCTURED_MULTI_FIELDS` and `STRUCTURED_OBJECT_LIST_FIELDS`.
  `finalize_candidate_value` for object-list fields iterates `values` and skips any element
  that is not itself a `list`. `_should_collect_dom_variants` calls
  `finalize_candidate_value("variants", list(candidates["variants"]))`; depending on the
  bucket shape this can return None and make the gate think existing variants are empty.
  This contributed to DOM variant rows being injected and then mis-merged. (Investigated;
  not the chosen fix path — see below.)
- DOM variant tier (`extract_variants_from_dom`) DOES correctly extract all 22 Nike sizes
  in label format with correct OOS once `variant_option_availability` reads disabled. The
  damage happened when DOM rows (label `M 5 / W 6.5`) merged with JSON-LD/adapter rows
  (token `5`): different size strings → didn't merge → later size-alias collapse dropped
  the OOS rows and `_drop_unanimous_variant_transport_fields` stripped availability when
  unanimous. Net live result: Nike 19 rows, all availability null.

---

## What is DONE and SAFE (landed, full suite green: 1230 passed)

1. `variant_option_availability` (dom_options.py) now reads, in priority order:
   - explicit `data-*` availability flags (`data-available`/`data-in-stock` false => OOS,
     true => in_stock; `data-oos`/`data-out-of-stock`/`data-sold-out`/`data-unavailable`
     truthy => OOS),
   - OOS class tokens (`outstock`, `soldout`, `unavailable`, `oos`, `no-stock`, ...),
   - `N left` stock text, explicit OOS text,
   - `disabled` / `aria-disabled` control or disabled class — ONLY when the option is NOT
     selected (preserves the selected+disabled regression contract). `disabled`/`checked`/
     `selected` are valueless boolean attrs, so detection uses `has_attr`, not truthiness.
   Helpers added: `_node_has_attr`, `_option_node_is_selected`, `_option_node_is_disabled`,
   `_option_flag_availability`.
2. The `<select><option>` branch in `extract_variants_from_dom` (dom_extraction.py) now
   also computes per-option availability via `variant_option_availability`.
3. Config (Rule 1 compliant) added to `config/extraction_rules/_variants.py` and exported
   via `_extra_exports.py`:
   - `VARIANT_OPTION_OUT_OF_STOCK_CLASS_TOKENS`, `VARIANT_OPTION_DISABLED_CLASS_TOKENS`,
     `VARIANT_OPTION_DISABLED_ATTRIBUTE_NAMES`,
     `VARIANT_OPTION_OUT_OF_STOCK_FLAG_ATTRIBUTE_NAMES`,
     `VARIANT_OPTION_AVAILABLE_FLAG_ATTRIBUTE_NAMES`, `VARIANT_OPTION_FLAG_FALSE_VALUES`,
     `VARIANT_OPTION_OUT_OF_STOCK_TEXT_PHRASES`, `VARIANT_OPTION_IN_STOCK_TEXT_PHRASES`,
     `VARIANT_OPTION_STOCK_LEFT_PATTERN`,
     `VARIANT_OPTION_CONTROL_SELECTOR`, `VARIANT_OPTION_CONTROL_SCAN_LIMIT`,
     `VARIANT_OPTION_CONTROL_KEY_ATTRIBUTES`.
4. Regression tests added in `tests/regression/test_detail_extractor_structured_sources.py`:
   - `test_variant_option_availability_treats_unselected_disabled_control_as_out_of_stock`
   - `test_variant_option_availability_reads_data_available_flag`
   (The end-to-end Nike swatch test was removed because the full-pipeline reconciliation is
   not finished; re-add it once reconciliation lands.)

Unit-verified behavior of `variant_option_availability`:
- selected+disabled => (None, None)   [contract preserved]
- aria-disabled / disabled (unselected) => out_of_stock
- data-available=false / data-oos => out_of_stock; data-available=true => in_stock
- soldout class, `N left`, disabled `<option>` => correct

Changed files (git status):
- M app/services/config/extraction_rules/_variants.py
- M app/services/config/extraction_rules/_extra_exports.py
- M app/services/extract/detail/variants/dom_options.py
- M app/services/extract/detail/variants/dom_extraction.py
- M tests/regression/test_detail_extractor_structured_sources.py
- ?? app/services/extract/detail/variants/dom_availability.py  (NEW, NOT wired — see below)

NOTE: `final_cleanup.py` was temporarily wired to the reconciler and then REVERTED. It is
currently back to baseline (no reconciliation call). Confirm it has no
`reconcile_variant_availability_from_dom` import/call before continuing.

---

## What is DRAFTED but NOT done / NOT correct yet

New module `app/services/extract/detail/variants/dom_availability.py` with
`reconcile_variant_availability_from_dom(record, *, soup)`. Intent:
1. Scope DOM option scan to variant containers via `variant_scope_roots(soup)` (to avoid
   reading disabled page chrome like "Go to previous reviews" / "Open Feedback features").
2. Build a join index from option controls keyed by normalized attrs
   (`VARIANT_OPTION_CONTROL_KEY_ATTRIBUTES`) + label/text + composite `value` tail
   (`10512_33x32` -> `33x32`). OOS evidence wins per key.
3. Match existing variant rows by sku/variant_id/barcode/axis values + option_values.
4. On match: set OOS (never upgrade a deterministic OOS), fill stock_quantity, and UPGRADE
   the row's axis value to the richer rendered label when current is a strict shorter token
   (`5` -> `M 5 / W 6.5`) via `_maybe_upgrade_axis_label`.
5. Append DOM-only OOS options the structured tier omitted, but only when the record has a
   single consistent axis (avoid fabricating cross-axis combos).

### KNOWN BUGS in the draft (must fix next session)
- NIKE: scoping via `variant_scope_roots` was added, but the standalone harness still showed
  a false positive `('Go to previous reviews', 'out_of_stock', 0)` in the EARLIER unscoped
  version. After scoping, RE-VERIFY the false positive is gone. Also the appended OOS rows
  must be in label format `M 5 / W 6.5` (they were, in the unscoped run). Re-run after scope
  change.
- BELK izod: after adding `variant_scope_roots` scoping, the harness returned ZERO OOS
  (`count=17`, OOS=[]). This means either (a) Belk's disabled size buttons are OUTSIDE the
  scope roots `variant_scope_roots` selects, or (b) the join keys for Belk
  (`value="10512_33x32"`, label text empty) didn't match the simulated structured rows
  (`size="33 x 30"`). The composite-tail key gives `33x32`; the structured size `33 x 32`
  normalizes to `33x32` — these SHOULD match. Most likely the scope roots don't include the
  Radix radiogroup, so options aren't collected. NEXT: debug `variant_scope_roots(soup)` on
  the Belk artifact; if it misses the Radix `[role=radiogroup]`/button container, either
  broaden scope or fall back to a dedicated variant-option selector with a chrome/nav
  exclusion list instead of full `variant_scope_roots`.

### Harness used (recreate as a temp script, delete after)
For Nike, simulate JSON-LD rows: sizes 6..18 (no 5/5.5/16) as
`[{"size": s, "option_values": {"size": s}}]`, call
`reconcile_variant_availability_from_dom(rec, soup=BeautifulSoup(html))`, expect appended
OOS `M 5 / W 6.5`, `M 5.5 / W 7`, `M 16 / W 17.5` and matched rows upgraded to label format.
For Belk izod, structured sizes like `32 x 30 ... 40 x 32`; expect `33 x 30` and `33 x 32`
flipped to out_of_stock.

---

## Remaining work (do in order)

1. Fix `variant_scope_roots` coverage for Belk Radix radiogroup OR replace the scope source
   in `_collect_dom_options` with `VARIANT_OPTION_CONTROL_SELECTOR` constrained by an
   explicit non-variant chrome exclusion (nav/header/footer/review/feedback/carousel). Make
   Nike (grid-selector inputs) and Belk (Radix role=radio buttons) both yield their OOS
   options and NO chrome false positives.
2. Confirm appended Nike OOS rows are label format `M 5 / W 6.5` and matched rows upgrade
   `5` -> `M 5 / W 6.5`.
3. Wire `reconcile_variant_availability_from_dom(record, soup=soup)` into
   `final_cleanup.py::_sanitize_ecommerce_detail_record`, placed AFTER
   `backfill_variants_from_dom_if_missing` and BEFORE
   `_reconcile_detail_availability_from_variants` (so parent availability re-derives from the
   corrected variant rows). Import is currently removed; re-add it.
4. Guard against the availability-stripping regression: `enforce_flat_variant_public_contract`
   -> `_drop_unanimous_variant_transport_fields` in
   `extract/variant_normalization/contract.py` drops a field when ALL rows share it. With
   reconciliation, `availability` is no longer unanimous once any OOS exists, so it survives.
   BUT verify: a fully in-stock product should still be allowed to drop per-row availability
   (parent carries it) — do NOT change that. Only ensure mixed in/out keeps per-row values.
5. Verify the user's exact complaint end-to-end on real artifacts:
   - Nike run 6/7: variants in `M x / W y` format, OOS sizes present and marked, in-stock
     marked or left as in_stock, full set restored (22 not 19).
   - Belk run 5 (all three): per-variant availability present, OOS variants flagged, and
     sku/barcode/stock_quantity NOT regressed. NOTE: in current state Belk variants come
     from `_source: json_ld` and LACK sku/barcode (JSON-LD doesn't carry them). The user
     explicitly complained sku/barcode/stock dropped — investigate whether the Belk ADAPTER
     (which DOES produce sku/barcode/availability/stock from `sku_*` arrays) should win over
     JSON-LD for variants. Check `_field_source_rank` / source priority for `variants` and
     why json_ld beat the adapter for Belk. This is a SEPARATE source-priority issue from the
     DOM availability gap and may be the bigger Belk fix.
6. Add end-to-end regression tests (real artifact fixtures) for both Nike and Belk under
   `-m regression`. Re-add the Nike disabled-swatch e2e test.
7. Run verify per AGENTS.md:
   ```powershell
   cd backend; $env:PYTHONPATH='.'
   .\.venv\Scripts\python.exe -m pytest tests -q            # full suite
   .\.venv\Scripts\python.exe -m pytest tests -m regression -q
   .\.venv\Scripts\python.exe run_extraction_smoke.py
   ```
8. Update `docs/INVARIANTS.md` Rule 3 only if the contract changes (per-variant availability
   is now DOM-reconciled). Update `docs/plans/ACTIVE.md` to point here while active.

---

## Guardrails / INVARIANTS to respect
- Fix upstream in extraction, not in publish/pipeline/export (Rule 2/4).
- Config (tokens, selectors, attr names, thresholds) lives ONLY in
  `app/services/config/...` (Rule 1) — already followed.
- Public flat variant contract: persisted/exported variant rows may only carry
  `sku, price, currency, url, image_url, availability, stock_quantity` + public axes
  (`PUBLIC_VARIANT_AXIS_FIELDS`) + top-level `variant_count`. `availability`/`stock_quantity`
  ARE in `FLAT_VARIANT_KEYS` (config/variant_policy.py) so they survive the boundary.
- Reconciliation must be additive/identity-preserving; never rebuild/reorder/strip existing
  rows. Never upgrade a deterministic `out_of_stock` to `in_stock`. Never mark OOS from
  absence of a signal — only from an explicit disabled/flag/class/text signal.
- Do NOT add site-specific `if "nike"`/`if "belk"` branches in generic paths (Rule 13). Keep
  it generic via config selectors/tokens.

## Key files
- `app/services/extract/detail/variants/dom_options.py` — per-option availability owner (DONE)
- `app/services/extract/detail/variants/dom_extraction.py` — DOM variant extraction; select path (DONE)
- `app/services/extract/detail/variants/dom_availability.py` — reconciliation (DRAFT, fix + wire)
- `app/services/extract/detail/assembly/final_cleanup.py` — wire reconciliation here (currently reverted/clean)
- `app/services/extract/variant_normalization/contract.py` — unanimous-field drop guard
- `app/services/extract/variant_dom_cues.py` — `variant_scope_roots` (scope source to debug for Belk)
- `app/services/config/extraction_rules/_variants.py` + `_extra_exports.py` — config (DONE)
- `app/services/adapters/nike.py`, `app/services/adapters/belk.py` — adapters (Belk source-priority question)
- Artifacts: `artifacts/runs/6|7/pages/1bcb5c849a75b86f.html` (Nike),
  `artifacts/runs/5/pages/*.html` (Belk); URLs in sibling `*.trace.json`.
