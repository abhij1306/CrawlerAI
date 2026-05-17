# Plan: Content, Article & Forum Thread Surfaces

**Created:** 2026-05-16
**Status:** COMPLETE
**Agent:** Codex
**Touches buckets:** Bucket 4 (Extraction), Bucket 2 (Orchestration config), Frontend

---

## Goal

Expand CrawlerAI beyond commerce/jobs/autos with deterministic extraction for general content, articles, and forum threads, while keeping the existing single-API path:

`acquire -> extract -> normalize -> persist`

No new endpoints. No new pipeline. No downstream export compensation.

---

## Architecture Principles

These govern every implementation decision in this plan. Codex must not deviate.

- **New logic in new files.** If a requirement has no corresponding existing file, create one. Do not bloat existing files with unrelated surface logic.
- **Existing files for extension only.** Existing files are modified only to add surface dispatch routing or minimal data entries. Business logic for new surfaces lives in new files.
- **No code inheritance between surfaces.** `content_detail`, `article_detail`, `forum_detail` are implemented independently in the same new module. Shared utilities are composed, not inherited.
- **Extraction stays pure.** Extractors return candidates. No direct record mutation. Derived fields (e.g. `reading_time` computed from `word_count`) are computed in post-extraction steps, not inside the extractor.
- **Table extraction is entirely new.** There is no existing table extraction implementation in the codebase. Treat it as a greenfield feature. Do not search for existing table code to extend.
- **Open-field passthrough is data-driven.** Do not add if-statement branches in `public_record_firewall.py`. Register field policy per surface in config.
- **Grep before writing.** Always grep for an existing pattern before implementing a new one.
- **Net-negative line count preferred.** Each slice should not add more lines than it removes when extending existing files.

---

## Surface Model

### Backend Surfaces Added

| Surface           | Description                                                  |
|-------------------|--------------------------------------------------------------|
| `content_detail`  | One record of readable text from any general web page        |
| `content_listing` | One record per row from a data table or repeated card grid   |
| `article_listing` | Structured article cards from a blog or news index           |
| `article_detail`  | Full article with author, date, and publication metadata     |
| `forum_detail`    | Forum thread OP body with reply/view thread metadata         |

`forum_listing` does not exist. Forum indexes are handled by `content_listing`. No forum listing surface, schema, extraction path, or frontend dispatch will be implemented.

### User-Facing Domain Picker

The existing two-button Domain toggle (Commerce | Jobs) becomes a dropdown:

```
Content
Commerce
Jobs
Automobiles
Article
Forum Thread
```

### Tab Behavior Per Domain

Tabs adapt when domain changes. Forum Thread has a single tab — no mode picker is rendered.

| Domain       | Tab 1           | Tab 2          |
|--------------|-----------------|----------------|
| Content      | Page Content    | Rows From Page |
| Commerce     | Category Crawl  | PDP Crawl      |
| Jobs         | Jobs Listing    | Job Detail     |
| Automobiles  | Listings        | Detail         |
| Article      | Article Feed    | Article Page   |
| Forum Thread | Forum Thread    | —              |

Single / Sitemap / Bulk tabs remain unchanged across all domains.

### Surface Dispatch Map

| Domain       | Tab             | Backend Surface      |
|--------------|-----------------|----------------------|
| Content      | Page Content    | `content_detail`     |
| Content      | Rows From Page  | `content_listing`    |
| Commerce     | Category Crawl  | `ecommerce_listing`  |
| Commerce     | PDP Crawl       | `ecommerce_detail`   |
| Jobs         | Jobs Listing    | `job_listing`        |
| Jobs         | Job Detail      | `job_detail`         |
| Automobiles  | Listings        | `automobile_listing` |
| Automobiles  | Detail          | `automobile_detail`  |
| Article      | Article Feed    | `article_listing`    |
| Article      | Article Page    | `article_detail`     |
| Forum Thread | Forum Thread    | `forum_detail`       |

---

## New Files Created By This Plan

These files do not currently exist. They are the primary implementation targets for new logic.

| File | Purpose |
|------|---------|
| `backend/app/services/extract/content_surface_extractor.py` | DOM extraction for `content_detail`, `article_detail`, `forum_detail`. Invoked by delegation from `detail_dom_extractor.py`. |
| `backend/app/services/extract/table_extractor.py` | Entirely new table detection, filtering, and structured extraction. Invoked by `detail_materializer.py` after prose extraction. |
| `backend/app/services/extract/content_listing_handler.py` | `content_listing` dual-path dispatch: table-row mode and card-scan mode. Invoked by `listing_extractor.py` when `surface == "content_listing"`. |
| `frontend/components/crawl/domain-surface-config.ts` | Domain dropdown options, per-domain tab definitions, surface dispatch map, default field rows, and UX copy. Extracted from `crawl-config-screen.tsx` to keep it thin. |

---

## Existing Files Modified By This Plan

Modifications are additive and minimal. No existing surface logic is changed.

| File | What Changes |
|------|-------------|
| `backend/app/services/config/field_mappings.exports.json` | Add new surface schemas, aliases, field type registrations |
| `backend/app/services/field_policy.py` | Add repair targets and browser retry targets for new surfaces |
| `backend/app/services/public_record_firewall.py` | Register `content_listing` table-row mode open-field policy via config lookup, not if-branch |
| `backend/app/services/structured_sources.py` | Add schema.org type mappings for Article, NewsArticle, BlogPosting, DiscussionForumPosting, WebPage |
| `backend/app/services/extract/detail_materializer.py` | Add surface dispatch routing for new surfaces → delegates to `content_surface_extractor.py`; calls `table_extractor.py` after prose extraction |
| `backend/app/services/extract/detail_tiers.py` | Add tier definitions for new detail surfaces |
| `backend/app/services/extract/detail_dom_extractor.py` | Add one delegation branch for content/article/forum surfaces → `content_surface_extractor.py` |
| `backend/app/services/listing_extractor.py` | Add `content_listing` dispatch → `content_listing_handler.py`; add typed-node recognition for article types |
| `backend/app/services/extract/listing_candidate_ranking.py` | Add article listing scoring signals |
| `backend/app/services/extract/listing_card_fragments.py` | Add article card fragment matching patterns |
| `backend/app/services/config/surface_hints.py` | Add generic article detail path hints if coverage improvement is verified |
| `frontend/components/crawl/shared.tsx` | Replace `deriveSurface(domain, module)` with new dispatch map; add `inferDomainFromSurface` entries |
| `frontend/components/crawl/crawl-config-screen.tsx` | Replace two-button domain toggle with dropdown; implement adaptive tabs per domain |
| `frontend/lib/api/types.ts` | Add new surface and domain union members |
| `frontend/lib/api/index.ts` | Update if `CrawlSurface` narrowing affects payload construction |

---

## Output Contract

Default output is structured deterministic data in `record.data`. Not raw HTML.

- `content` is plain cleaned text.
- `tables` is a structured array from meaningful embedded tables on detail pages. **This is a new feature with no existing implementation.**
- `title` and `url` are required high-value fields on all surfaces.
- Raw HTML stays in artifacts and provenance only (`raw_html_path`, artifact export). Never in `record.data`.
- Markdown and cleaned HTML exports are out of scope for this plan.

### Table Output Shape (all detail surfaces)

```json
{
  "tables": [
    {
      "context": "Technical Specifications",
      "headers": ["Feature", "Value"],
      "rows": [
        {"Feature": "Display", "Value": "6.3 inch Super Retina XDR"},
        {"Feature": "Chip", "Value": "A18 Pro"}
      ]
    }
  ]
}
```

Context source priority: `<caption>` → nearest previous heading in same content container → ARIA label or labelled-by → section title.

Drop tables that are: layout, nav, form, calendar, single-cell, empty, or where more than 50% of cells are links or buttons.

### `content_listing` Open-Field Contract

When surface is `content_listing` and extraction mode is table-row, header cells become record field names. These are arbitrary (e.g. `Country`, `Population`). They are not in `CANONICAL_SCHEMAS["content_listing"]`.

**Implementation:** Register `content_listing` as an open-field surface in `field_mappings.exports.json` under a new `OPEN_FIELD_SURFACES` key. `public_record_firewall.py` checks this registry — no if-branch. Records in table-row mode carry `record.meta.extraction_mode = "table_rows"`. The firewall applies permissive field passthrough only when both conditions are met: surface is in `OPEN_FIELD_SURFACES` and `extraction_mode == "table_rows"`.

### `content_listing` Dual-Path Dispatch

The new `content_listing_handler.py` applies this decision rule in order:

1. If the largest meaningful content block is a `<table>` with `<th>` headers and ≥ 3 data rows → **table-row mode**: emit one record per `<tbody><tr>`, normalize header cells to field names (lowercase, underscores, strip punctuation), tag `extraction_mode = "table_rows"`.
2. Otherwise → **card-scan mode**: delegate to existing card matching in `listing_extractor.py` with a relaxed gate of `title + url`.

A failed `content_listing` extraction is a listing failure. It does not fall back to a `content_detail` record.

---

## Schemas

### `content_detail`
```python
["title", "url", "content", "summary", "headings",
 "image_url", "additional_images", "tags", "category",
 "breadcrumbs", "language", "word_count", "tables"]
```

### `content_listing`
```python
["title", "url", "summary", "image_url", "category"]
# Arbitrary field passthrough enabled in table-row mode via OPEN_FIELD_SURFACES registry.
```

### `article_listing`
```python
["title", "author", "publication_date", "url",
 "image_url", "category", "summary", "source_name"]
```

### `article_detail`
```python
["title", "url", "author", "publication_date", "content", "summary",
 "category", "tags", "image_url", "additional_images",
 "source_name", "language", "word_count", "reading_time", "tables"]
```

### `forum_detail`
```python
["title", "author", "publication_date", "content", "summary", "url",
 "category", "tags", "reply_count", "view_count", "last_reply_date", "tables"]
```

---

## Field Aliases

Add to `field_mappings.exports.json` scoped to new surfaces only. Do not add global aliases that could contaminate ecommerce/job field resolution.

```
author          -> byline, writer, posted_by, creator, contributor, articleAuthor
content         -> body, article_body, articleBody, full_text, post_body, text, page_content, main_content
summary         -> excerpt, abstract, intro, lead, teaser, meta_description
headings        -> sections, outline, toc, table_of_contents
breadcrumbs     -> breadcrumb, nav_path, page_path
source_name     -> publisher, site_name, publication
reply_count     -> comments, comment_count, num_replies, responses
view_count      -> views, page_views, read_count
word_count      -> wordCount, word_length
reading_time    -> read_time, readingTime, time_to_read
last_reply_date -> last_activity, last_post_date
language        -> lang, locale
tables          -> table, data_tables, spec_tables, comparison_tables
```

Field type registrations (add in Slice 1):
- `LONG_TEXT_FIELDS`: `content`, `summary`
- `STRUCTURED_MULTI_FIELDS`: `headings`, `tags`, `breadcrumbs`, `additional_images`
- `STRUCTURED_OBJECT_LIST_FIELDS`: `tables`
- `INTEGER_VALUE_FIELDS`: `reply_count`, `view_count`, `word_count`, `reading_time`

---

## `reading_time` Derivation

This is a derived field, not extracted. Computation runs after extraction, not inside the extractor.

Source priority:
1. DOM: `.reading-time`, `[itemprop="timeRequired"]`, `[data-reading-time]`
2. Structured data: `timeRequired` on Article types
3. Computed: `ceil(word_count / 200)` — only if `word_count` is present

Do not emit `reading_time` if neither structured data nor `word_count` is available.

---

## Article Listing Gate

Require: `title + url + (date OR author OR summary)`

At least one qualifying signal (date, author, or summary) must be present. `title + url` alone is insufficient. This prevents nav menus and link lists from matching.

Boost signals: `<article>`, `.post-item`, `.blog-entry`, `.news-item`, date elements, author elements, image.

---

## `WebPage` Schema.org Priority

Almost every page carries a `WebPage` JSON-LD node. Do not globally lift its priority in `_json_ld_node_priority`. Commerce and job pages must not rank generic page metadata above product and job payloads.

Gate `WebPage` usage by surface in `detail_materializer.py` where `surface` is known. `WebPage` is a valid source only for `content_detail`.

---

## Acceptance Criteria

- [x] `CANONICAL_SCHEMAS` contains `content_detail`, `content_listing`, `article_listing`, `article_detail`, `forum_detail`
- [x] `forum_listing` does not exist anywhere in the codebase — no schema, no extraction path, no frontend dispatch
- [x] `OPEN_FIELD_SURFACES` registry exists in config and contains `content_listing`
- [x] `public_record_firewall.py` uses registry lookup, not an if-branch, for open-field passthrough
- [x] Field aliases added and scoped to new surfaces
- [x] `content_detail` returns one record with `title/content/url` when visible text exists
- [x] `content_listing` table-row mode emits one record per meaningful row with header-cell field names
- [x] `content_listing` table-row records carry `extraction_mode = "table_rows"` and pass firewall
- [x] `content_listing` card-scan mode emits records for pages with repeated cards and `title + url`
- [x] Article listing gate enforces `title + url + (date OR author OR summary)`
- [x] `forum_detail` extracts OP body and thread metadata; no listing surface exists
- [x] `forum_detail` schema includes `summary`
- [x] `reading_time` derivation follows DOM → structured data → computed fallback; not emitted if unavailable
- [x] `WebPage` structured source used only for `content_detail`; does not affect ecommerce/job/automobile
- [x] `tables` field is new and implemented only in Slice 7; schemas carry the field definition from Slice 1
- [x] `tables` available on all detail surfaces including `ecommerce_detail`, `job_detail`, `automobile_detail`
- [x] Table text removed from `content` prose via DOM-level operation, not string filtering
- [x] `content_surface_extractor.py` is a new file; content/article/forum DOM logic does not bloat `detail_dom_extractor.py`
- [x] `table_extractor.py` is a new file with no external dependencies except BeautifulSoup/lxml
- [x] `content_listing_handler.py` is a new file; dual-path dispatch logic does not bloat `listing_extractor.py`
- [x] Frontend domain picker is a dropdown, not a two-button toggle
- [x] Forum Thread domain renders a single tab with no mode picker
- [x] Content tabs use "Page Content" / "Rows From Page" labels
- [x] Article tabs use "Article Feed" / "Article Page" labels
- [x] `deriveSurface` updated for all new surfaces
- [x] Existing ecommerce/job/automobile extraction passes all existing tests unmodified
- [x] `python -m pytest tests -q` exits 0
- [x] Smoke: `content_detail` — consulting/docs page extracts `title/content/url`
- [x] Smoke: `content_listing` table-row mode — data table emits header-keyed records
- [x] Smoke: `article_listing` — blog index extracts `title/author/date/url` rows
- [x] Smoke: `article_detail` — article page extracts `title/author/date/content/image_url`
- [x] Smoke: `forum_detail` — thread page extracts `title/content` plus at least one of `reply_count/view_count`
- [x] Smoke: any detail page with a spec table exposes it in `tables`

---

## Do Not Touch

- `acquisition/*` — same fetch pipeline handles new surfaces
- `pipeline/persistence.py` — surface-agnostic
- `publish/*` — verdict logic is surface-agnostic; do not compensate for extraction bugs here
- `product_intelligence/*` — unrelated
- `data_enrichment/*` — unrelated
- Variant extraction logic — not applicable to content/article/forum
- Export endpoints — current JSON/CSV/artifacts exports unchanged

---

## Handoff Notes For New Chat

1. Read `docs/plans/ACTIVE.md`.
2. Read this plan in full.
3. Read `docs/INVARIANTS.md` Rule 1, Rule 3, Rule 5, Rule 7, Rule 8, Rule 10.
4. Read `docs/CODEBASE_MAP.md` only if file owner is unclear.
5. Grep before writing any code.

Current architecture facts:

- Main extraction entry: `backend/app/services/extraction_runtime.py`
- Detail extraction owners: `backend/app/services/extract/detail_materializer.py`, `detail_tiers.py`, `detail_dom_extractor.py`. There is no `detail_extractor.py`.
- Listing extraction owner: `backend/app/services/listing_extractor.py`, helpers under `backend/app/services/extract/listing_*`
- Surface schemas and aliases: `backend/app/services/config/field_mappings.exports.json` via `field_mappings.py`
- Public output filter: `backend/app/services/public_record_firewall.py`
- Frontend surface derivation: `frontend/components/crawl/shared.tsx` → `deriveSurface(crawlDomain, crawlTab)`; must be replaced

---

## Slices

### Slice 1: Field Schema, Aliases, And Type Registrations
**Status:** DONE

**Existing files modified:**
- `backend/app/services/config/field_mappings.exports.json`
- `backend/app/services/config/field_mappings.py` — only if new primitive constants are genuinely needed
- `backend/tests/services/test_config_imports.py`

**What:**

Add to `CANONICAL_SCHEMAS`: all five new surfaces with schemas defined above.

`forum_listing` must not be added. If it appears anywhere, remove it.

Add all field aliases defined in the Aliases section above. Scope them to new surfaces only. Verify no alias bleeds into ecommerce or job field resolution.

Add `tables` as an allowed field to the three new detail schemas now. Do not implement extraction here — that is Slice 7. The field must exist in the schema before Slice 7 runs.

Add `OPEN_FIELD_SURFACES = ["content_listing"]` to `field_mappings.exports.json`. This is the registry the firewall reads in Slice 2.

Register new field types:
- `LONG_TEXT_FIELDS`: `content`, `summary`
- `STRUCTURED_MULTI_FIELDS`: `headings`, `tags`, `breadcrumbs`, `additional_images`
- `STRUCTURED_OBJECT_LIST_FIELDS` (add key if absent): `tables`
- `INTEGER_VALUE_FIELDS`: `reply_count`, `view_count`, `word_count`, `reading_time`

Add to `DOM_HIGH_VALUE_FIELDS`:
- `content_detail`: `content`, `summary`
- `article_detail`: `content`, `summary`
- `forum_detail`: `content`

Add to `DOM_OPTIONAL_CUE_FIELDS`:
- `content_detail`: `tags`, `category`, `headings`
- `article_detail`: `tags`, `category`, `reading_time`
- `forum_detail`: `tags`, `reply_count`, `view_count`

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_config_imports.py -q
```

---

### Slice 2: Field Policy And Public Boundary
**Status:** DONE

**Existing files modified:**
- `backend/app/services/field_policy.py`
- `backend/app/services/public_record_firewall.py`
- `backend/tests/services/test_field_policy*.py`
- `backend/tests/services/test_public_record_firewall*.py`

**What:**

In `field_policy.py`, add `SURFACE_FIELD_REPAIR_TARGETS`:
- `content_detail`: `["title", "content"]`
- `article_detail`: `["title", "content", "author"]`
- `forum_detail`: `["title", "content"]`

Add `SURFACE_BROWSER_RETRY_TARGETS`:
- `content_detail`: `["title", "content"]`
- `article_detail`: `["title", "content"]`
- `forum_detail`: `["title", "content"]`

In `public_record_firewall.py`, implement open-field passthrough using the `OPEN_FIELD_SURFACES` registry from Slice 1. Do not add an if-branch hardcoding `content_listing`. The logic must be: load `OPEN_FIELD_SURFACES` from config; if `record.surface in OPEN_FIELD_SURFACES` and `record.meta.get("extraction_mode") == "table_rows"`, allow arbitrary field names. Any future open-field surface is added to config only — firewall code does not change again.

Verify field exclusion: content/article/forum fields must not appear in ecommerce/job/automobile records and vice versa.

Keep public output clean: no raw HTML, no internal page context, no empty fields, no `_`-prefixed fields in `record.data`.

Do not create a second surface policy layer. Use existing `canonical_fields_for_surface`, `field_allowed_for_surface`, `public_record_data_for_surface` flows.

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_field_policy*.py tests/services/test_public_record_firewall*.py -q
```

---

### Slice 3: Structured Source Mapping
**Status:** DONE

**Existing files modified:**
- `backend/app/services/structured_sources.py`
- `backend/app/services/extract/detail_materializer.py`
- `backend/app/services/shared/field_coerce.py` — only if scalar coercion needs small additions
- `backend/tests/services/test_structured_sources*.py`
- `backend/tests/services/test_detail_extractor_structured_sources.py`

**What:**

Add deterministic schema.org field mappings:

`Article`, `NewsArticle`, `BlogPosting`:
- `headline` / `name` → `title`
- `articleBody` / `text` → `content`
- `author.name` → `author`
- `datePublished` → `publication_date`
- `publisher.name` → `source_name`
- `image` → `image_url`

`DiscussionForumPosting`:
- `headline` / `name` → `title`
- `text` / `articleBody` → `content`
- `author.name` → `author`
- `datePublished` → `publication_date`
- `commentCount` → `reply_count`

`WebPage`:
- Safe fallback for `content_detail` only.
- Map `name` / `headline` → `title`, `description` → `summary`.
- Do not use `WebPage` as a source on any other surface.

Do not globally lift `WebPage` priority in `_json_ld_node_priority`. Gate `WebPage` usage by surface in `detail_materializer.py` where `surface` is known.

All extracted fields must pass through candidates and normal field arbitration. No direct record mutation.

**Note for Slice 5:** Slice 5 also modifies `detail_materializer.py`. The `WebPage` surface-gate added here must be preserved. Slice 5 must not regress it.

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_structured_sources*.py tests/services/test_detail_extractor_structured_sources.py -q
```

---

### Slice 4: Content And Article Listing Extraction
**Status:** DONE

**New file created:**
- `backend/app/services/extract/content_listing_handler.py`

**Existing files modified:**
- `backend/app/services/listing_extractor.py`
- `backend/app/services/extract/listing_candidate_ranking.py`
- `backend/app/services/extract/listing_card_fragments.py`
- `backend/app/services/config/surface_hints.py`
- `backend/app/services/config/domain_profiles.py`
- `backend/tests/services/test_listing_extractor*.py`

**What:**

**New file — `content_listing_handler.py`:**

This file owns all `content_listing` extraction logic. `listing_extractor.py` calls it when `surface == "content_listing"` and returns.

Implement dual-path dispatch (evaluated in order):

1. **Table-row mode** — triggers when: largest meaningful content block is a `<table>` with `<th>` headers and ≥ 3 `<tbody><tr>` data rows.
   - Emit one record per row.
   - Normalize `<th>` cells to field names: lowercase, spaces to underscores, strip punctuation.
   - Include `url` only if the row contains a meaningful anchor link.
   - Set `record.meta.extraction_mode = "table_rows"` on each record.
   - Reject: layout tables, nav tables, form tables, calendar tables, single-column tables.

2. **Card-scan mode** — all other cases.
   - Gate: `title + url` (relaxed, no domain-specific signal required for content surface).
   - Delegate to existing card matching infrastructure in `listing_extractor.py`.

A `content_listing` failure is a listing failure. It must not fall back to a `content_detail` record.

**Existing files — minimal extensions only:**

In `listing_extractor.py`: add one dispatch branch for `surface == "content_listing"` → `content_listing_handler.handle(page, surface)`. Return result directly.

Extend typed-node recognition to include:
```python
("product", "jobposting", "article", "newsarticle", "blogposting")
```
`DiscussionForumPosting` is not included — there is no `forum_listing` surface.

In `listing_candidate_ranking.py`: add article listing scoring signals — boost `<article>`, `.post-item`, `.blog-entry`, `.news-item`, date elements, author elements, image.

In `listing_card_fragments.py`: add article card fragment patterns.

**Article listing gate** (enforced in `listing_extractor.py`):
- Require: `title + url + (date OR author OR summary)`
- `title + url` alone is rejected — prevents nav/archive pollution.

Update `SURFACE_PAIRS`:
- `content_listing` <-> `content_detail`
- `article_listing` <-> `article_detail`
- `forum_detail` has no listing pair

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_listing_extractor*.py -q
```

---

### Slice 5: Detail Extraction For Content, Articles, Forums
**Status:** DONE

**New file created:**
- `backend/app/services/extract/content_surface_extractor.py`

**Existing files modified:**
- `backend/app/services/extract/detail_materializer.py`
- `backend/app/services/extract/detail_tiers.py`
- `backend/app/services/extract/detail_dom_extractor.py`
- `backend/app/services/config/extraction_rules.py`
- `backend/tests/services/test_detail_extractor*.py`

**Critical:** This slice modifies `detail_materializer.py`. Slice 3 also modified this file for `WebPage` surface-gating. Preserve those changes. Grep for the `WebPage` gate before editing.

**What:**

**New file — `content_surface_extractor.py`:**

This file owns all DOM extraction for `content_detail`, `article_detail`, and `forum_detail`. It is not called directly by the pipeline — `detail_dom_extractor.py` delegates to it for these surfaces. It returns candidates (not records) for normal field arbitration.

Implement three surface extraction functions in this file:

`extract_content_detail(dom, surface)`:
- `title`: `<h1>` or best page title
- `content`: readable main body as plain text — strip nav/sidebar/footer before extraction, not after
- `summary`: meta description → leading paragraph
- `headings`: `h2`/`h3` within main body only
- `word_count`: count of whitespace-delimited tokens in `content`
- `image_url`: first meaningful image in main content area

`extract_article_detail(dom, surface)`:
- Structured source fields come from Slice 3 and are already in candidates by the time this runs. DOM extraction is the fallback layer only.
- DOM fallback content selectors: `article`, `[itemprop="articleBody"]`, `.article-body`, `.post-content`, `.entry-content`
- DOM fallback author selectors: `.author`, `[rel="author"]`, `[itemprop="author"]`, `.byline`
- DOM fallback date selectors: `time[datetime]`, `[itemprop="datePublished"]`, `.post-date`, `.published`
- `reading_time` derivation (post-extraction, not in extractor): DOM first (`.reading-time`, `[itemprop="timeRequired"]`, `[data-reading-time]`), then structured data `timeRequired`, then `ceil(word_count / 200)`. Omit if `word_count` is also absent.

`extract_forum_detail(dom, surface)`:
- `content`: OP/thread body only — not reply bodies
- `summary`: meta description or OP excerpt
- DOM content selectors: `.post-body`, `.message-content`, `.thread-content`, `.bbp-reply-content`
- `reply_count` / `view_count`: from structured data or visible metadata spans
- Reply threading is out of scope. Store counts only.

Shared utilities within this file (not exposed externally):
- `_sanitize_dom(dom)`: strip nav, footer, sidebar, cookie banners, ads before any text extraction
- `_extract_meta_description(dom)`: `<meta name="description">` and OpenGraph equivalents

**Existing files — minimal extensions only:**

`detail_dom_extractor.py`: add one dispatch branch — if surface in `{"content_detail", "article_detail", "forum_detail"}`, call `content_surface_extractor.extract(dom, surface)` and return. One branch, one import, nothing else changes.

`detail_materializer.py`: add surface routing for new surfaces → delegates to `content_surface_extractor.py`. Preserve `WebPage` gate from Slice 3.

`detail_tiers.py`: add tier definitions for new detail surfaces.

`extraction_rules.py`: add extraction rules for new surfaces if needed. Grep for existing pattern before adding.

All surfaces: ecommerce-only variant/price/title repair must remain gated to ecommerce surfaces. Do not allow it to fire on content/article/forum.

No hard cap on `content` field size in this slice. If tests reveal pathological output, add a config-owned limit — never hardcode it.

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_detail_extractor*.py -q
```

---

### Slice 6: Frontend Surface Model
**Status:** DONE

**New file created:**
- `frontend/components/crawl/domain-surface-config.ts`

**Existing files modified:**
- `frontend/components/crawl/crawl-config-screen.tsx`
- `frontend/components/crawl/shared.tsx`
- `frontend/lib/api/types.ts`
- `frontend/lib/api/index.ts` — only if `CrawlSurface` narrowing affects payload construction
- `frontend/components/crawl/crawl-config-screen.test.tsx`
- `frontend/components/crawl/crawl-config-screen.prefill.test.tsx`

**What:**

**New file — `domain-surface-config.ts`:**

Extract all domain/tab/surface configuration into this file. `crawl-config-screen.tsx` imports from it. This keeps the screen component thin and the config independently testable.

Define and export:
- `DOMAIN_OPTIONS`: ordered list for dropdown — `["content", "commerce", "jobs", "automobiles", "article", "forum_thread"]`
- `DOMAIN_TABS`: per-domain tab definitions with labels and surface keys
- `SURFACE_DISPATCH`: `(domain, tab) => CrawlSurface` map
- `DEFAULT_FIELDS`: per-domain per-tab default field rows
- `DOMAIN_COPY`: per-domain helper text shown below the tab row

```typescript
// Domain tab definitions
const DOMAIN_TABS = {
  content:      [{ key: "page_content", label: "Page Content" }, { key: "rows_from_page", label: "Rows From Page" }],
  commerce:     [{ key: "category_crawl", label: "Category Crawl" }, { key: "pdp_crawl", label: "PDP Crawl" }],
  jobs:         [{ key: "jobs_listing", label: "Jobs Listing" }, { key: "job_detail", label: "Job Detail" }],
  automobiles:  [{ key: "listings", label: "Listings" }, { key: "detail", label: "Detail" }],
  article:      [{ key: "article_feed", label: "Article Feed" }, { key: "article_page", label: "Article Page" }],
  forum_thread: [{ key: "forum_thread", label: "Forum Thread" }],  // single tab
};

// Surface dispatch
const SURFACE_DISPATCH: Record<string, CrawlSurface> = {
  "content:page_content":      "content_detail",
  "content:rows_from_page":    "content_listing",
  "commerce:category_crawl":   "ecommerce_listing",
  "commerce:pdp_crawl":        "ecommerce_detail",
  "jobs:jobs_listing":         "job_listing",
  "jobs:job_detail":           "job_detail",
  "automobiles:listings":      "automobile_listing",
  "automobiles:detail":        "automobile_detail",
  "article:article_feed":      "article_listing",
  "article:article_page":      "article_detail",
  "forum_thread:forum_thread": "forum_detail",
};

// Default fields per domain/tab
const DEFAULT_FIELDS = {
  "content:page_content":      ["title", "content", "url"],
  "content:rows_from_page":    ["title", "url"],
  "article:article_feed":      ["title", "publication_date", "author", "url"],
  "article:article_page":      ["title", "author", "publication_date", "content", "url"],
  "forum_thread:forum_thread": ["title", "author", "content", "reply_count", "view_count", "url"],
  // commerce/jobs/automobiles defaults: carry forward existing values unchanged
};
```

**Existing files — minimal extensions only:**

`shared.tsx`: replace `deriveSurface(domain, module)` with a lookup into `SURFACE_DISPATCH` from the new config file. Update `inferDomainFromSurface` to handle new surfaces for run workspace labels.

`crawl-config-screen.tsx`: replace two-button Domain toggle with a dropdown bound to `DOMAIN_OPTIONS`. Render tabs from `DOMAIN_TABS[domain]`. Forum Thread renders one tab — mode picker does not render. All tab labels, default fields, and helper copy come from `domain-surface-config.ts`. No configuration values live in the screen component.

`types.ts`: add to `CrawlDomain` union: `"content"`, `"article"`, `"forum_thread"`. Add to `CrawlSurface` union: all five new surfaces.

Domain memory lookup continues to key on `normalized_domain + surface`. `content_detail` and `content_listing` are distinct memory keys.

Legacy route params `module=category|pdp` may remain as compatibility shims but must not drive UI state for new domains.

Do not add landing-page style UI, modals, or new UI primitives.

**Verify:**
```bash
cd frontend && npm run build
cd frontend && npm test -- crawl-config-screen
```

---

### Slice 7: Table Extraction
**Status:** DONE

**This slice runs only after Slices 1–6 pass tests.**

**New file created:**
- `backend/app/services/extract/table_extractor.py`

**Existing files modified:**
- `backend/app/services/extract/detail_materializer.py`
- `backend/app/services/config/field_mappings.exports.json` — add `tables` to `ecommerce_detail`, `job_detail`, `automobile_detail` schemas
- `backend/app/services/public_record_firewall.py` — if structured object list shape validation needs extension
- `backend/tests/services/test_detail_extractor*.py`
- `backend/tests/services/test_public_record_firewall*.py` — if touched

**What:**

**This is an entirely new feature.** There is no existing table extraction implementation in the codebase. Do not search for table extraction code to reuse or extend.

**New file — `table_extractor.py`:**

This file has one public function: `extract_tables(dom, content_container) -> list[dict]`.

It takes the sanitized DOM and the resolved main content container element. It returns zero or more table objects in the shape defined in the Output Contract section.

Dependencies: only BeautifulSoup or lxml (whichever the project uses for DOM work). No pipeline imports. Fully unit-testable with raw HTML input.

Context resolution (in priority order):
1. `<caption>` element within the table
2. Nearest preceding heading (`h1`–`h4`) within the same content container
3. ARIA `aria-label` or `aria-labelledby` resolved text
4. Enclosing section or accordion label

Header normalization: lowercase, strip punctuation, replace spaces with underscores.

Filtering — drop tables that match any of these:
- No `<th>` header cells
- Fewer than 2 columns
- Fewer than 2 data rows
- More than 50% of cells contain only links or buttons
- Table is outside the resolved content container (i.e. in nav, footer, sidebar)
- Table is a form (contains `<input>`, `<select>`, `<textarea>`)
- Table cells contain date navigation patterns (calendar)

Table text removal from `content` prose: after calling `extract_tables`, remove the corresponding `<table>` elements from the DOM *before* prose text extraction runs. This is a DOM mutation, not string filtering. It prevents table cell text from appearing both in `tables` and in `content`.

Write targeted tests for:
- Table mid-article (prose continues before and after)
- Table at page edge (first or last element in content container)
- Multiple tables on one page
- Tables with merged cells (`colspan`/`rowspan`) — extract best-effort, no error
- Filtered tables (nav, form, calendar) — verify they are absent from output
- Page with no meaningful tables — verify `tables` is absent or empty list from `record.data`

**Existing files — minimal extensions only:**

`detail_materializer.py`: after prose extraction for any detail surface, call `table_extractor.extract_tables(dom, container)`. Attach result to `record.data["tables"]` if non-empty. This is a single call site.

Add `tables` to `ecommerce_detail`, `job_detail`, `automobile_detail` schemas in `field_mappings.exports.json`. These surfaces already have `tables` in the new detail schemas from Slice 1.

**Verify:**
```bash
cd backend && python -m pytest tests/services/test_detail_extractor*.py tests/services/test_listing_extractor*.py -q
```

---

### Slice 8: Acceptance Smoke Tests
**Status:** DONE

**Files:**
- `backend/tests/services/` — new test files for new surfaces
- `backend/test_site_sets/` — if adding curated manifests
- `backend/run_extraction_smoke.py` — only if smoke harness needs a new fixture hook

**What:**

All tests verify public `record.data`, not raw internal candidates.

Unit tests:
- All 5 new surface schema resolutions load correctly
- `content_detail` routes to detail extraction, not listing
- `content_listing` table-row mode: emits records with header-cell field names, `extraction_mode` tag present, records pass firewall
- `content_listing` card-scan mode: emits records for repeated card pages
- `content_listing` failure does not produce a `content_detail` fallback record
- Article listing gate rejects `title + url` only — requires at least one qualifying signal
- `forum_listing` does not exist (negative assertion against schema registry)
- Structured source mapping for each new schema.org type produces correct candidates
- `tables` field populated on detail pages with meaningful tables
- `tables` absent (or empty) on pages with no meaningful tables
- Table text absent from `content` prose when tables are present
- `reading_time` computed as fallback when DOM and structured data are absent but `word_count` is present
- `reading_time` absent when `word_count` is also absent

Test fixtures (static HTML, no network):
- `content_detail`: consulting/service page
- `content_detail`: documentation/help page
- `content_listing` table-row mode: pricing grid or government data table
- `content_listing` card-scan mode: repeated card grid
- `article_listing`: blog or news index page
- `article_detail`: article with JSON-LD + DOM fallback
- `article_detail`: article with embedded data table — verify `tables` populated and prose is deduplicated
- `forum_detail`: thread page with OP body, reply count, view count

**Verify:**
```bash
cd backend && python -m pytest tests -q
cd backend && python run_extraction_smoke.py
```

Run broader smoke only if shared extraction behavior changed:
```bash
cd backend && python run_acquire_smoke.py commerce
cd backend && python run_test_sites_acceptance.py
```

---

### Slice 9: Docs And Handoff Cleanup
**Status:** DONE

**Files:**
- `docs/BUSINESS_LOGIC.md`
- `docs/CODEBASE_MAP.md`
- `docs/INVARIANTS.md` — only if new hard contracts emerge
- `docs/frontend-architecture.md`
- `docs/plans/ACTIVE.md`

**What:**

`BUSINESS_LOGIC.md`:
- Add content/article/forum surface decisions and output contracts
- Document `content_listing` dual-path dispatch and open-field passthrough
- Document `tables` as new universal detail field — entirely new feature, no prior implementation
- Document `forum_listing` removal rationale: forum indexes served by `content_listing`

`CODEBASE_MAP.md`:
- Add new files to Bucket 4: `content_surface_extractor.py`, `table_extractor.py`, `content_listing_handler.py`
- Update only if owners/files changed — do not pad

`frontend-architecture.md`:
- Document domain dropdown replacing two-button toggle
- Document adaptive tabs per domain
- Document `domain-surface-config.ts` as the single source of truth for domain/tab/surface config
- Document Forum Thread single-tab behavior

`INVARIANTS.md`:
- Add only if implementation produces a new hard contract that must not regress
- Do not pad with descriptions of normal behavior

Mark slices DONE only after their verify commands pass.

**Verify:**
```bash
cd backend && python -m pytest tests -q
```

---

## Future Surface Taxonomy

### Covered By This Plan

| Surface      | Examples                                    | Status          |
|--------------|---------------------------------------------|-----------------|
| Commerce     | product pages, catalogs, marketplaces       | existing        |
| Jobs         | job boards, ATS pages, career pages         | existing        |
| Automobiles  | dealer inventory, auto marketplaces         | existing        |
| Content      | docs, landing pages, help, wiki, consulting | this plan       |
| Article      | blogs, news, editorials, press releases     | this plan       |
| Forum Thread | forums, Q&A, discussion boards              | this plan       |
| Tables       | embedded spec/comparison/data tables        | this plan (new) |

### Future On-Demand Surfaces

| Gap         | Examples                                   | Recommendation                 |
|-------------|--------------------------------------------|--------------------------------|
| Real estate | Zillow, Rightmove, property listings       | Add only when needed           |
| Events      | Eventbrite, Meetup, conferences            | Add only when needed           |
| Profiles    | people pages, team pages, directories      | Usually content now; add later |
| Reviews     | Yelp, TripAdvisor, G2                      | Future if aggregation matters  |
| Recipes     | food blogs with structured ingredients     | Future vertical                |
| Media/video | YouTube, podcast pages, transcripts        | Different extraction model     |

`content_detail` is the catch-all. Any page that does not fit another surface should still yield useful readable text from this surface.
