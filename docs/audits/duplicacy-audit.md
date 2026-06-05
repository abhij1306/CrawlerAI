## Backend DOM traversal duplication audit complete. Here are the consolidation targets:

P0 — Byte-identical duplicate function

variant_choice_traversal.py:167 and dom_extraction.py:137 both define _variant_input_label() with identical logic; only minor attr-guard differences separate them. One must be re-exported from the other.

P1 — 7 separate ancestor-walk implementations

All files implement their own while parent is not None: ... parent = parent.parent loop with proxy guards:

structured_sources.py — _has_itemscope_ancestor (L523) + _belongs_to_nested_itemscope (L532)
variant_choice_traversal.py — resolve_variant_group_name (L410), iter_variant_choice_groups (L724), _variant_choice_container_for_input (L811)
listing_signals.py — _ancestor_anchor_nodes (L95)
selector_engine.py — _is_in_cross_link_container (L396)
A single walk_ancestors(node, predicate, max_depth, stop_at=None) utility would replace all seven.

P1 — Sibling-label walk

Same while sibling is not None: if sibling.name == "label": return sibling idiom appears inline in variant_choice_traversal.py:179 (_nearby_variant_group_name) and is also embedded in the duplicated _variant_input_label functions at both files.

P2 — hasattr(node, "find") / hasattr(node, "select") guard-before-action

~20 call sites across variant_choice_traversal.py and dom_extraction.py repeat this duck-typing guard. A single safe_find(node, *a, **kw) helper (mirroring the existing safe_select at selector_engine.py:408) would eliminate the boilerplate.

P2 — node.get_text(" ", strip=True) used 60+ times

section_extraction.py:109–110 already defines a local node_text(node) wrapper but keeps it module-private. Generalizing it and routing other call sites through it would also centralize text cleaning.

P3 — .select() without SelectorSyntaxError guard

safe_select() at selector_engine.py:408 exists but is bypassed in browser_readiness.py, runtime.py, raw_signals.py, site_link_discovery.py, surface_resolver.py, extraction_retry_decision.py, and content_surface_extractor.py — each calling soup.select(...) or container.select(...) directly, crashing on bad selectors instead of returning [].

P3 — for child in node.children: (4 instances)

selector_engine.py:332, inline_scalar.py:91, section_extraction.py:266, and content_surface_extractor.py:397 all iterate .children, discriminate NavigableString/Tag, and extract text. Minor helpers like iter_tag_children(node) / iter_text_children(node) could share the type-filter logic.

Highest-impact first move: remove the duplicated _variant_input_label copy and route both through a single definition.


## Here is the full duplication map across backend/app extraction and DOM modules:

1. Whitespace Collapse
20+ inline instances of " ".join(str(value or "").split()).strip() scattered across:

File	Lines	Variant
services/normalizers/__init__.py	52	plain
services/extraction_html_helpers.py	60, 107, 123, 133	plain, with & replace
services/field_policy.py	119, 303	plain
services/dom/xpath_service.py	299, 462	+ .lower()
services/acquisition/browser_detail.py	607, 704, 744, 754	+ .lower()/.upper()
services/structured_sources.py	509	node get_text(" ", strip=True)
services/dom/image_extraction.py	103	plain
services/design_system.py	467	plain (no .strip())
services/product_intelligence/matching.py	364	+ .casefold()
services/selector_suggestions.py	110	+ .lower()
services/extract/listing_candidate_ranking.py	622, 715–716, 723, 762	title normalization
services/extract/field_candidates/structured_payloads.py	44	+ & replace + .lower()
services/acquisition/browser_interstitial.py	73	node text
services/ucp_audit/reporting.py	187	plain
services/pipeline/sitemap.py	84, 86	plain
services/crawl/sitemap_resolver.py	710, 717	plain
services/monitor_change_detection.py	304	+ .lower()
services/monitor_alert_rules.py	168	+ .lower()
services/dom/listing_card_fragments.py	435	selector normalization
Canonical utility exists at services/shared/text_coerce.py:36-51 (clean_text, whitespace_re = re.compile(r"\s+")) — all inline instances should call this.

2. Empty Value Checks
40+ occurrences of value in (None, "", [], {}) / value not in (None, "", [], {}):

services/shared/field_coerce.py — 9 locations (lines 170, 210, 336, 359, 409, 692, 726, 771, 932)
services/dom/selector_engine.py — lines 551, 597, 624, 658
services/data_enrichment/deterministic.py — lines 458, 671, 689
services/structured_sources.py — lines 494, 563
services/extract/detail/price/parsing.py — lines 65, 123, 170
services/adapters/shopify.py — lines 625, 627
services/adapters/myntra.py — lines 293, 297, 301
services/normalizers/__init__.py — lines 94, 249, 255, 294
services/extract/field_candidates/collection.py — line 19
services/extract/variant_normalization/deduplication.py — line 198
services/extract/variant_normalization/contract.py — lines 48, 218
services/pipeline/extract_records.py — lines 194, 414
services/pipeline/extraction_loop.py — line 651
services/product_intelligence/matching.py — line 628
services/llm/prompt_rendering.py — line 416
services/llm/payloads.py — line 19
services/confidence.py — line 46
services/ucp_audit/catalog_crawl.py — lines 88, 207
services/selector_self_heal.py — line 463
services/public_record_firewall.py — line 99
services/monitor_change_detection.py — line 295
services/pipeline/direct_record_fallback.py — lines 64, 133
services/js_state/variant_options.py — lines 78, 196
services/extract/detail/variants/dom_options.py — line 50 (also includes False)
Recommendation: Centralize as is_blank(value) in a shared primitives file.

3. Null-Text String Filtering (semantically empty strings)
Three separate implementations of the same concept:

services/shared/text_coerce.py:81 — lowered in {"nan", "none", "null"} + separate "undefined" check
services/shared/field_coerce.py:595 — cleaned.strip().casefold() in {"none", "null", "- / null", "n/a", "na"}
services/config/public_record_policy.py:109 — {"default", "null", "na", "n/a", "none", "all", "other", ""}
Recommendation: Unify into is_null_text(text) in text_coerce.py.

4. Title Noise Detection
Canonical: services/shared/text_coerce.py:76-108 (is_title_noise)
Called in 10+ files:

services/extract/structured_listing_handler.py — lines 24, 65, 67
services/extract/listing_signals.py — lines 57, 257, 439, 475, 481, 555
services/listing_extractor.py — lines 75, 229, 322, 326, 331
services/pipeline/extract_records.py — lines 235, 338
services/extract/detail/identity/core.py — lines 76, 531
services/extract/detail/assembly/record_assembly.py — line 202
services/extract/detail/assembly/title_scorer.py — lines 20, 75, 97
services/extract/detail/assembly/dom_fallbacks.py — lines 36, 93
Duplicated placeholder sets scattered separately:

services/extract/detail/assembly/record_sanitization.py:86 — CANDIDATE_PLACEHOLDER_VALUES
services/extract/detail/identity/core.py:34,102 — same CANDIDATE_PLACEHOLDER_VALUES
services/config/detail_extraction_constants.py:31,61–62,73 — DETAIL_BASE_PLACEHOLDER_TITLE_PATTERNS, DETAIL_PLACEHOLDER_TITLE_PATTERNS
services/extract/variant_normalization/size_color_extraction.py:80–87,177–182 — VARIANT_PLACEHOLDER_VALUES, VARIANT_PLACEHOLDER_PREFIXES
One-off: lstrip("+") at services/extract/detail/assembly/record_sanitization.py:297 not covered by is_title_noise.

5. Price Normalization Overlap
Two near-identical Decimal normalization pipelines:

services/normalizers/__init__.py:135 — _normalize_shared_price_decimal_text
services/normalizers/__init__.py:145 — _canonicalize_decimal_candidate
Both duplicate the same replace(",", "") / comma-as-decimal-separator / digit-count-check logic. They differ only in parameter wrapping.

Repeated artifact/placeholder filtering in two places:

services/extract/detail/text/sanitizer.py:234-238, 353-357 — artifact_price_values frozenset + _price_candidate_is_artifact
services/extract/detail/assembly/record_sanitization.py:479-480 — hardcoded "price", "original_price" key checks
6. Spec / Attribute Normalization Duplication
Canonical: services/shared/field_coerce.py:672-717 (coerce_product_attributes, _clean_product_attribute_dict, _clean_product_attribute_value)

Re-implemented independently: services/extract/detail/assembly/record_sanitization.py:560-625 (_normalize_detail_tables, _table_headers, _normalized_table_row, _table_is_size_guide) — repeats same clean_text(key) and value not in (None, "", [], {}) logic.

Repeated tokenization: " ".join(...).casefold().split() for feature/spec text in 6 files:

services/extract/detail/variants/pruning.py:394
services/extract/variant_structural_pruning.py:266
services/shared/url_utils.py:129
services/js_state/state_normalizer/_identity.py:167
services/data_enrichment/shopify_catalog.py:745,754
services/extract/variant_identity_merge.py:53
Top Consolidation Targets
Group	Target Utility	~Duplicated In
whitespace_collapse	clean_text() in text_coerce.py	20+ inline sites
empty_filter	is_blank(value) in shared primitives	40+ sites
null_text	is_null_text(text) in text_coerce.py	3 separate sets
title_placeholder	Unified placeholder registry	4 separate constants
price_artifacts	Single normalize_decimal_price + artifact set	2 functions + 1 inline check
attr_normalize	Single coerce_product_attributes for tables	1 separate _normalize_detail_tables


## Overlap Audit: Config vs Service Code
A. Surface/path tokens duplicated in services (not using detail_path_hints / config)
Token set	Config source hardcoded in service	File(s) and location
/products/, /product/, /p/, /item/, /jobs/, /job/	_listing_html_detail_anchor_count	backend/app/services/acquisition/browser_page_helpers.py:111-118
/products/, /product/, /p/, /item/, /jobs/, /job/	_listing_html_detail_anchor_count	backend/app/services/acquisition/browser_page_helpers.py:111-118
/products/, /product/, /p/, /item/, /jobs/, /job/	_html_has_listing_signals	backend/app/services/crawl/site_link_discovery.py:325-327
/product/, /products/, /p/, ?piid=, &piid=, variant=	_anchor_node_has_variant_signal	backend/app/services/extract/variant_choice_traversal.py:293
/products/, /product/, /p/, /dp/, /item/	_node_has_detail_like_link	backend/app/services/extract/listing_card_fragments.py:537
B. Expand/toggle selectors duplicated in service (derive from config but redefined locally)
Selector/blocks	Config source	Duplicated in service
[aria-expanded='false'], button[aria-controls], [role='button'][aria-controls], [role='tab'][aria-controls], size selector, size-selector, open-size-selector	backend/app/services/config/extraction_rules/_common.py:100-116 and _exports.json	backend/app/services/acquisition/browser_detail.py:340-347, backend/app/services/acquisition/browser_detail.py:401-406
C. DOM operator constants with mismatched defaults between config and service
Constant	Config extract rule value	Effective service default	File(s)
MAX_SELECTOR_MATCHES	12	12 (match)	backend/app/services/config/extraction_rules/_variants.py:279, backend/app/services/dom/selector_engine.py:104, backend/app/services/dom/image_extraction.py:97
SCOPE_SCORE_MAIN_WEIGHT	4000	4000 (match)	backend/app/services/config/extraction_rules/_variants.py:276, backend/app/services/dom/selector_engine.py:105
SCOPE_SCORE_PRIORITY_WEIGHT	2000	2000 (match)	backend/app/services/config/extraction_rules/_variants.py:277, backend/app/services/dom/selector_engine.py:107
SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT	1000	1000 (match)	backend/app/services/config/extraction_rules/_variants.py:278, backend/app/services/dom/selector_engine.py:110
DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS	24	8 (MISMATCH)	backend/app/services/config/extraction_rules/_detail.py:136, backend/app/services/dom/section_extraction.py:25
DETAIL_LONG_TEXT_MAX_SECTION_CHARS	12000	1200 (MISMATCH)	backend/app/services/config/extraction_rules/_detail.py:137, backend/app/services/dom/section_extraction.py:26
D. Threshold literals outside config but matching config scope
Value / token	Where hardcoded in service	Context
0.4	backend/app/services/crawl/sitemap_resolver.py:750	thin-result confidence check (matches SURFACE_RESOLVER_LOW_CONFIDENCE = 0.4 in surface_detection.py:120)
0.4	backend/app/services/extract/detail/identity/shell_filter.py:167	confidence threshold for shell filtering (domain of SURFACE_RESOLVER_LOW_CONFIDENCE)
productish_nodes >= 4 / product_links >= 3 / price_hits >= 2	backend/app/services/crawl/site_link_discovery.py:329-330	Listing detection thresholds; no config constants found for 4, 3, 2, 20_000
E. Summary of risk
Path tokens in browser_page_helpers.py and site_link_discovery.py are stale relative to SURFACE_DETAIL_PATH_HINTS in backend/app/services/config/surface_hints.py (which includes /dp/, /p/, /pd/, /spd/, /proddetail/, etc., that these services do not check).
DETAIL_LONG_TEXT_MAX_SECTION_* has a real config/sync bug: config exports say 24 blocks / 12000 chars, but DOM code reads a hardcoded default of 8 / 1200 and never imports the canonical config values.
Expand selectors in browser_detail.py are defined both in _common.py and literally in the service file; if one moves the other is silently out of sync.
0.4 low-confidence threshold exists in two service files independent of SURFACE_RESOLVER_LOW_CONFIDENCE.
The highest-value fixes are the DETAIL_LONG_TEXT_* default sync and replacing the literal path-token tuples in browser_page_helpers.py:111-118, site_link_discovery.py:325-327, variant_choice_traversal.py:293, and listing_card_fragments.py:537 with detail_path_hints(...).


## Duplicated Variant Extraction Logic
1. DOM vs JS State Variants
_option_names (JS state) and _structured_product_option_names (structured pipeline) — identical fallback chain: name → title → label → raw string, each separately implemented
Backfill context propagation — _backfill_nested_variant_context (JS state), _backfill_variant_shared_fields_from_record (normalization backfill), and inline logic in dom_extraction.py — 3 independent implementations of "propagate parent price/color/image into child variant rows when missing"
2. Structured Payloads vs JS State
Full variant row normalization — _structured_variant_rows vs _normalize_variant — same conceptual pipeline (extract sku, barcode, price, availability, color, size, build option_values), using different field-name fallback chains, zero shared code
Variant URL from ID — identical urlparse + parse_qsl reassembly with variant= param in both variant_rows.py and _variant_mapping.py
3. Option Axes Extraction (×5 sites)
option_values construction implemented independently in: JS state normalizer, structured variant rows, structured selected-option values, DOM availability rewrite, sanitization
_PUBLIC_AXIS_FIELDS / _MATRIX_AXIS_FIELDS / _public_variant_axis_key — 3 separate re-derivations of "is this a public variant axis key?"
4. SKU Mapping (×6 sites)
variant_id then sku fallback — same pattern in variant_identity_merge.py, variant_structural_pruning.py, variant_normalization/backfill.py, js_state/_variant_mapping.py, field_candidates/variant_rows.py, dom_availability.py
SKU terminal token extraction — re.split(r"[^a-z0-9]+", sku.casefold()) separately implemented in variant_structural_pruning.py and hydration.py
5. Availability Handling (×4+ sites)
Availability string normalization (instock/lowstock → in_stock) re-implemented in _variant_rows.py, dom_options.py, dom_availability.py, final_cleanup.py
safe_int(value) -> int | None via int(str(value).strip()) in try/except — duplicated 3+ times
Parent-derivation rule (all variants out_of_stock → parent out_of_stock) only in final_cleanup.py, not reusable
6. Price Gap Detection (×3 sites)
_price_is_cents_copy in money_repair.py and detail_price_is_cent_magnitude_copy in price/core.py — near-identical Decimal comparison with same tolerance constant
_price_is_low_signal_copy in money_repair.py vs reconcile_parent_price_against_variant_range in price/core.py — both answer "should we replace parent price?" with similar magnitude checks, coded independently
7. Merge/Dedup (×2 sites)
merge_variant_rows in variant_identity_merge.py and _dedupe_variant_rows in deduplication.py — both implement identical 2-pass merge: identity key then semantic key, using same helpers
Top Consolidation Priorities
Priority	Target	Files	Lines
P0	Unified variant row normalizer	extract/variant_row.py	~40 lines removed
P0	Unify _dedupe_variant_rows → call merge_variant_rows	deduplication.py	~40 lines removed
P1	Shared option-values builder + cleaner	variant_identity_merge.py	5 call sites
P1	normalize_availability_string into js_state/helpers.py	4 call sites	small
P1	resolve_variant_identity_fields helper	6 call sites	2 lines each
P2	Canonical is_cent_magnitude_copy in price/parsing.py	money_repair.py + price/core.py	small
P2	is_public_variant_axis in variant_axis.py	3 call sites	tiny


## Here are the tests with overlapping coverage and implied duplicated implementation paths:

1. Price Normalization — 5+ modules, overlapping parsing logic
Test file	What it tests	Implementation module
test_normalizers.py:69-114	normalize_decimal_price — currency prefixes, suffixes, dot-thousands, negatives	app/services/normalizers.py
test_field_value_core.py:147-150	decimal_for_shared_price — European decimal format (1.234,56)	app/services/shared/field_coerce.py
test_field_value_core.py:732-780	coerce_field_value("price", {value, formattedPrice, priceCurrency})	app/services/shared/field_coerce.py
test_field_value_core.py:709-711	extract_currency_code("Rs. 3,990.00") / "INR 499"	app/services/shared/field_coerce.py
test_state_mappers.py:187-223	JS state prices.currentPrice treated as cents when no currency	app/services/js_state/state_normalizer.py
test_state_mappers.py:22-108	Shopify price: 9900 → "109" (cents)	same
Duplication implication: Three separate price-parsing paths (normalize_decimal_price, decimal_for_shared_price, JS state cents detection) likely each contain their own regex for stripping currency symbols, handling European grouping, and detecting negative values. The formattedPrice vs raw value preference logic in field_coerce.py is a fourth price interpretation path.

2. Text/Content Sanitization — 3+ modules with overlapping noise-stripping
Test file	What it tests	Implementation module
test_shared_text_coerce.py:17-28	clean_text — entities, whitespace, CSS-in-JS noise, escaped quotes, unicode	app/services/shared/text_coerce.py
test_field_value_core.py:845-849	clean_text(".css-7u5e79{...} The Legend of Zelda") → stripped	same clean_text
test_materials_sanitizer.py:10-57	_clean_materials_pollution — preserves real composition, strips editorial boilerplate	app/services/extract/detail/text/sanitizer.py
test_detail_quality_cleanup.py:146-160	sanitize_detail_long_text — dedupes title mentions, strips measurement noise	same sanitizer.py
test_field_value_core.py:479-487	coerce_field_value("product_details", "['Leather upper...']") → joined semicolons	field_coerce.py
Duplication implication: _clean_materials_pollution and sanitize_detail_long_text both detect and strip repetitive boilerplate text (measurement blocks, editorial fluff), but likely implement their own heuristics rather than sharing the same trim/dedup primitive as clean_text.

3. Variant Normalization — 4+ modules with overlapping concerns
Test file	What it tests	Implementation module
test_normalizers.py (40+ tests)	normalize_variant_record — UI noise drop, axis dedup, color/size promotion, SKU suffix hydration, backfill, currency enforcement	variant_normalization.py + submodules
test_shared_variant_logic.py (20+ tests)	resolve_variants — Cartesian ordering, dedupe, partial option_values	variant_identity_merge.py
test_shared_variant_logic.py:69-121	variant_option_value_is_noise — UI controls, shipping tokens, CTA buttons	variant_option_value.py
test_shared_variant_logic.py:313-376	resolve_variant_group_name — size/shipping/cookie consent rejection	variant_choice_traversal.py
test_shared_variant_logic.py:808-866	extract_variants_from_dom — size-over-color, fulfillment noise filter	detail/variants/dom_extraction.py
test_variant_scope.py	variant_scope_roots, select_variant_nodes, variant_node_in_noise_context	variant_dom_cues.py
test_field_value_core.py:1120-1128	merge_variant_rows — axis-only rows deduped by axis key	field_coerce.py
Duplication implication: variant_option_value_is_noise and normalize_variant_record both filter UI noise ("Save to Wishlist", "Buy Now", "-", "+"). The noise token list appears independently in both modules. Similarly, Cartesian deduplication logic exists in both resolve_variants and normalize_variant_record's cross-product collapse.

4. URL/Image Normalization — 4 modules with overlapping URL resolution
Test file	What it tests	Implementation module
test_shared_url_utils.py:16-31	absolute_url — relative, bare host, query/hash, path repair	app/services/shared/url_utils.py
test_field_value_core.py:28-45	absolute_url — bare host, edge-hyphen labels	same
test_field_value_core.py:661-679	strip_tracking_query_params — Etsy click tracking, preserves variant=	same
test_field_value_core.py:860-913	extract_urls — punctuation trimming, concatenated URL rejection, placeholder filter	same
test_field_value_dom.py:123-167	extract_page_images — CDN dedup by resized variants, preserves non-resize query params	dom/image_extraction.py
test_detail_image_cleanup.py:14-48	_detail_image_candidate_is_usable — Walmart PDP URLs rejected, store-scope dedup	extract/detail/images/cleanup.py
test_detail_image_cleanup.py:64-73	canonical_image_url — Shopify store identity with query params	same
Duplication implication: absolute_url exists in both url_utils.py and field_coerce.py (tested in both files). Placeholder image rejection (via.placeholder.com, Shopify no-image-*) is tested in url_utils.py AND field_value_core.py:1055-1064, suggesting the check is duplicated rather than shared. Tracking-param stripping is independently implemented in field_coerce.py vs possibly elsewhere.

5. Brand Normalization — 3+ modules with overlapping inference logic
Test file	What it tests	Implementation module
test_shared_text_coerce.py:60-83	coerce_brand_text — strips pipe/en-dash taglines, preserves "Nike Inc."	app/services/shared/field_coerce_text.py
test_field_value_core.py:49-93	coerce_field_value("brand", "https://...", ...) — rejects URL-like, rejects bare host, keeps "foo:bar"	field_coerce.py
test_field_value_core.py:916-944	infer_brand_from_title_marker / infer_brand_from_product_url	field_coerce.py
test_normalizers.py:225-258	repair_ecommerce_detail_record_quality backfills brand from URL/identity	final_cleanup.py
test_detail_quality_cleanup.py:112-133	same repair for Endclothing numeric brand, Barrow from title	same
Duplication implication: Brand URL rejection (coerce_field_value rejecting https://... as brand) and URL-based brand inference (infer_brand_from_product_url) likely contain overlapping URL-parsing logic. The tagline-stripping regex in coerce_brand_text and the brand repair logic in final_cleanup.py may both independently strip marketing suffixes.

6. Color Normalization — 2+ modules with overlapping rejection/filter logic
Test file	What it tests	Implementation module
test_field_value_core.py:951-1035	coerce_field_value("color", ...) — rejects single digits, all-caps codes (SMDB, OLGG), tracking pixels, extracts from prefixed copy	field_coerce.py
test_normalizers.py:820-834	normalize_variant_record promotes "Smoke Green (sold out)" misfiled-as-size to color	variant_normalization.py
test_normalizers.py:1496-1522	drops numeric shade code size duplicates ("209" when color is "209 Mocha Latte")	same
test_shared_variant_logic.py:69-121	variant_option_value_is_noise — filters non-color UI values	variant_option_value.py
Duplication implication: All-caps internal code rejection (SMDB, BLK, AQT, OLGG) is tested in field_value_core.py and implicit in test_detail_image_cleanup.py:32-51 (rejects other colorway codes). This logic likely lives independently in both the color coercion path and the image family-matching path.

7. Availability/Stock Normalization — 3 modules
Test file	What it tests	Implementation module
test_field_value_core.py:577-588	public_record_data_for_surface normalizes "OUT_OF_STOCK" → "out_of_stock"	public_record_firewall.py
test_normalizers.py:490-495	normalize_value("availability", "https://schema.org/LimitedAvailability") → "limited_stock"	normalizers.py
test_state_mappers.py:15-18	availability_value normalizes "out-of-stock", "unavailable", "0"	js_state/helpers.py
Duplication implication: Three separate availability normalizers — schema.org URL mapping, enum casing normalization, and JS state alias mapping. Each likely has its own mapping table.

8. Coercion Primitives — foundational but tested in isolation
test_shared_coerce_primitives.py tests safe_int, coerce_int, object_dict, object_list, string_list — these are used by every coercion path above but tested independently, implying they're imported and reused rather than duplicated. This is the one clean shared layer.

Summary: Highest-Impact Duplication Candidates
Price parsing across 4 modules (normalizers.py, field_coerce.py, state_normalizer.py, js_state/helpers.py) — merge into a single price_parser.py
Variant noise filtering across 3 modules (variant_option_value.py, variant_normalization.py, normalizers.py) — merge UI noise token lists
URL resolution + placeholder detection across 4 modules (url_utils.py, field_coerce.py, dom/image_extraction.py, detail/images/cleanup.py) — absolute_url exists in two places; placeholder filter exists in two places
Brand tagline stripping across 2 modules (field_coerce_text.py, final_cleanup.py) — consolidate suffix-stripping regex
Availability enum normalization across 3 modules — consolidate into field_coerce.py or a shared availability.py