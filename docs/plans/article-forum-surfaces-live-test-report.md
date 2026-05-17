# Article & Forum Surfaces Live Test Report

**Date:** 2026-05-16  
**Plan:** `docs/plans/article-forum-surfaces-plan.md`  
**Live corpus:** `backend/artifacts/article_forum_surface_live_corpus.json`  
**Smoke report:** `backend/artifacts/extraction_smoke/20260516T172223Z__article_forum_surfaces_live.json`

## Scope

Four common public sites were tested across the new surfaces:

- Python Docs: `content_detail`
- Wikipedia: `content_listing`, `content_detail` with `tables`
- Python Blog: `article_listing`, `article_detail`
- Meta Discourse: `forum_detail`

## Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_content_article_forum_surfaces.py -q
.\.venv\Scripts\python.exe run_extraction_smoke.py --corpus artifacts/article_forum_surface_live_corpus.json --groups article_forum_surfaces_live --timeout 90
```

## Results

| Surface | Site | Expected | Result |
| --- | --- | --- | --- |
| `content_detail` | Python Docs Tutorial | `title`, `url`, `content` | PASS |
| `content_listing` | Wikipedia Population Table | >= 3 table-row records | PASS, 20 records |
| `content_detail` + `tables` | Wikipedia Population Detail Tables | `title`, `url`, `content`, `tables` | PASS |
| `article_listing` | Python Blog Index | >= 3 article records with `title`, `url` | PASS, 10 records |
| `article_detail` | Python Blog Detail Article | `title`, `url`, `content`, `publication_date` | FAIL |
| `forum_detail` | Meta Discourse Welcome Thread | `title`, `url`, `content` | PASS |

Unit test result: `7 passed`.

Live smoke result: `5 passed / 1 failed`.

## Finding 1: `article_detail` Misses DOM Publication Date

**Severity:** medium  
**Surface:** `article_detail`  
**URL:** `https://blog.python.org/2026/05/python-3150-beta-1`

The page contains a valid DOM date:

```text
time[datetime] = 2026-05-07T00:00:00.000Z
```

But the final record only contains:

```text
title, url, content, summary, language, word_count, reading_time
```

`publication_date` is missing.

### Root Cause

The DOM extractor can extract the date through `_date_text()` in `content_surface_extractor.py`.

The issue is before that: `DetailTierExecutor` can skip the DOM tier when pre-DOM tiers already produce enough confidence. `publication_date` is requested but has no configured DOM pattern in `EXTRACTION_RULES["dom_patterns"]`, so `requested_content_extractability()` does not mark it extractable. Result: DOM tier is skipped, even though `time[datetime]` exists.

### Fix

Config-owned fix. Do not hardcode in service code.

Add a `publication_date` DOM pattern under `EXTRACTION_RULES.dom_patterns` in `backend/app/services/config/field_mappings.exports.json`:

```json
"publication_date": "time[datetime], [itemprop='datePublished'], .post-date, .published"
```

Then add/adjust a regression test where an `article_detail` page has enough JS/structured content to permit early exit, but is missing `publication_date` until DOM runs. Expected: requested `publication_date` forces DOM completion and the final record includes the date.

Suggested verify:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_content_article_forum_surfaces.py tests/services/test_detail_extractor*.py -q
.\.venv\Scripts\python.exe run_extraction_smoke.py --corpus artifacts/article_forum_surface_live_corpus.json --groups article_forum_surfaces_live --timeout 90
```

## Notes

- Initial stale Python Blog `.html` URL returned only 473 bytes. Retested with a current URL extracted from the live Python Blog index. Failure persisted.
- Meta Discourse passed for `title`, `url`, and OP `content`; this smoke did not require `reply_count` or `view_count`.
- The test run prints an existing local secret warning about default bootstrap admin config. It did not affect extraction results.

---

# Extended 10-Site Live Pass

**Date:** 2026-05-16  
**Live corpus:** `backend/artifacts/article_forum_surface_extended_corpus.json`  
**Smoke report:** `backend/artifacts/extraction_smoke/20260516T172845Z__article_forum_surfaces_extended.json`

## Extended Scope

Ten more common public targets:

- MDN docs
- Django docs
- Node.js docs
- Wikipedia tables
- Hacker News listing
- GitHub Blog listing
- GitHub Blog detail
- MDN Blog detail
- Stack Overflow question
- Reddit thread

## Extended Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_extraction_smoke.py --corpus artifacts/article_forum_surface_extended_corpus.json --groups article_forum_surfaces_extended --timeout 90
```

## Extended Smoke Results

| Surface | Site | Smoke Result | Data Audit |
| --- | --- | --- | --- |
| `content_detail` | MDN JavaScript Guide | PASS | BAD: thin content, 101 chars |
| `content_detail` | Django Tutorial | PASS | OK |
| `content_detail` | Node.js Intro | PASS | OK |
| `content_listing` | Wikipedia HTTP Status Codes | PASS | BAD: extracted related links, not table rows |
| `content_listing` | Hacker News Front Page | PASS | BAD: listing noise includes header/time rows |
| `article_listing` | GitHub Blog Index | FAIL: 0 records | BAD: article cards not recognized |
| `article_detail` | GitHub Blog Article | FAIL: missing `publication_date` | BAD: content only 42 chars |
| `article_detail` | MDN Blog Article | FAIL: missing `publication_date` | Mostly OK content, date missing |
| `forum_detail` | Stack Overflow Question | PASS | OK, but slow browser path: 86s |
| `forum_detail` | Reddit Thread | FAIL: missing `content` | BAD: verification shell |

Extended smoke result: `6 passed / 4 failed`.

Data audit result: `4 clean / 6 bad or degraded`.

## New Finding 2: Sanitizer Deletes Main Content When Ancestor Class Contains `sidebar`

**Severity:** high  
**Surfaces:** `content_detail`, `article_detail`  
**Examples:** MDN docs, GitHub Blog article

Evidence:

```text
MDN original main text length: 10697
MDN after content sanitizer: 0
Final content: 101 chars

GitHub Blog original/clean main text length: ~20219
GitHub after content sanitizer: 0
Final content: 42 chars
```

Root cause:

`content_surface_extractor._sanitize_dom()` decomposes every node matching:

```text
[class*='sidebar' i]
```

This deletes valid ancestor containers:

- MDN: `layout__2-sidebars-inline`
- GitHub Blog: `no-sidebar`

Because the ancestor is decomposed, the actual article/main body disappears before extraction.

Fix:

- Do not decompose broad `class*=sidebar` matches when the node is `body`, `main`, `article`, or contains a large content block.
- Prefer targeted sidebar removal:

```text
aside, [role='complementary'], .sidebar, .right-sidebar, .left-sidebar, [class~='sidebar']
```

- Add regression fixtures:
  - MDN-style wrapper class `layout__2-sidebars-inline`
  - GitHub-style body class `no-sidebar`
  - Assert content remains > 500 chars.

## New Finding 3: Article Detail Date Extraction Has Selector Coverage Gap

**Severity:** medium  
**Surfaces:** `article_detail`, likely `forum_detail`

Examples:

- Python Blog article has `time[datetime]` but final record misses `publication_date`.
- GitHub Blog article has `time[datetime]` but final record misses `publication_date`.
- MDN Blog article has visible date in `.date`, but `_date_text()` does not scan `.date`.

Root causes:

- `publication_date` has no config DOM pattern, so requested missing dates may not force DOM completion.
- DOM date selector list is too narrow.

Fix:

- Add config-owned `EXTRACTION_RULES.dom_patterns.publication_date`:

```json
"publication_date": "time[datetime], [itemprop='datePublished'], .post-date, .published, .posted-on, .date"
```

- Extend `_date_text()` only if config pattern alone does not feed the content surface extractor.
- Regression:
  - Requested `publication_date` + `time[datetime]` must force DOM completion.
  - `.date` fixture must populate `publication_date`.

## New Finding 4: `content_listing` Table-Row Mode Falls Through To Card Scan On Wikipedia Tables

**Severity:** high  
**Surface:** `content_listing`

Example:

`https://en.wikipedia.org/wiki/List_of_HTTP_status_codes`

Smoke passed with 20 records, but sample output was related links:

```text
This article is semi-protected.
List of FTP server return codes
List of HTTP header fields
```

This is a false pass. It did not emit HTTP status-code rows.

Likely root cause:

The table-row trigger is too strict for common Wikipedia tables, then card-scan fallback accepts unrelated page links.

Fix:

- Tighten fallback: if meaningful tables exist but table-row mode rejects them, emit failure or table diagnostics instead of unrelated card scan.
- Support common table shapes:
  - header row without explicit `<thead>`
  - `wikitable`
  - first row `<th>` + following `<td>` rows
- Add data-quality assertions for table-row mode:
  - records must include header-derived keys
  - `_extraction_mode == "table_rows"`
  - do not count generic link-card records as pass.

## New Finding 5: `content_listing` Card Scan Is Too Loose For Hacker News

**Severity:** medium  
**Surface:** `content_listing`

Example:

`https://news.ycombinator.com/news`

Sample output includes non-story rows:

```text
Hacker News
Apply to YC
30 minutes ago
```

Root cause:

Relaxed `title + url` gate accepts page chrome and metadata rows as listing records.

Fix:

- Add utility-title filtering for `content_listing` card mode.
- Prefer repeated structural rows with outbound/story links over header/nav links.
- For HN-like tables, group `.athing` story row with its subtext row.

## New Finding 6: GitHub Blog Article Listing Extracts Zero Records

**Severity:** medium  
**Surface:** `article_listing`

Example:

`https://github.blog/`

Evidence:

```text
article count: 21
.post-card count: 28
article h2 a count: 17
time[datetime] count: 25
records: 0
```

Root cause:

Article cards are present, but current listing card extraction/ranking does not recognize GitHub Blog card structure.

Fix:

- Add article card fragment patterns for GitHub-style `.post-card` / `article h2 a` layouts.
- Ensure article gate can pair title URL with nearby `time[datetime]`.
- Regression fixture with multiple `article.post-card` cards.

## New Finding 7: Reddit Verification Shell Is Not Classified As Blocked

**Severity:** medium  
**Surface:** `forum_detail`

Example:

`https://www.reddit.com/r/Python/comments/1fybncq`

Evidence:

```text
status_code: 200
title: Reddit - Please wait for verification
html_len: 8450
final fields: title, url
content: missing
```

Root cause:

Acquisition/block detection does not classify Reddit verification pages as blocked or challenged. Extraction then emits a shell record with no content.

Fix:

- Add blocked-page signature:

```text
Reddit - Please wait for verification
```

- For `forum_detail`, reject records with shell titles and empty content.
- Optional acquisition retry path: browser retry may help, but must not be a downstream extraction fallback.

## New Finding 8: Stack Overflow Forum Detail Works But Is Slow

**Severity:** low  
**Surface:** `forum_detail`

Example:

`https://stackoverflow.com/questions/11227809/...`

Result:

```text
PASS
method: browser
elapsed: 86s
content length: 74785
publication_date: 2012-06-27 13:51:36Z
reply_count present
```

Risk:

The output is valid, but browser fallback cost is high. This is acceptable for blocked/JS-heavy pages but should be tracked if forum testing expands.

Fix:

- No correctness fix required now.
- Add performance budget only if forum smoke becomes part of default CI.

## Priority Fix Order

1. Fix broad sidebar sanitizer deletion. This causes severe false success on real docs/articles.
2. Add `publication_date` DOM pattern and regression. This affects multiple article sites.
3. Fix `content_listing` false pass when tables exist but row mode fails.
4. Tighten `content_listing` card-scan noise filtering.
5. Add GitHub Blog article-card fixture/pattern.
6. Add Reddit verification blocked signature and reject shell forum records.

---

# Implementation Update

**Date:** 2026-05-16  
**Status:** implemented and verified  
**Final smoke report:** `backend/artifacts/extraction_smoke/20260516T175634Z__article_forum_surfaces_extended.json`

## Fixes Applied

- Content sanitizer no longer deletes valid `main`/`article` containers or ancestors such as `layout__2-sidebars-inline` and `no-sidebar`.
- Content/detail surfaces now run their own sanitizer over original DOM, so generic pre-cleaning cannot drop metadata such as MDN `.date`.
- `article_detail` date extraction now covers `time[datetime]`, `datePublished`, `.post-date`, `.published`, `.posted-on`, and `.date`.
- `article_detail` chooses the largest article body candidate, preventing related-card `<article>` elements from winning over the real post body.
- `content_listing` no longer falls through to unrelated card scan when table-row intent exists but row extraction rejects the table.
- `article_listing` has article-specific card selectors and integrity support fields, so GitHub Blog cards extract.
- Article listing ranking no longer applies ecommerce structural URL rejection to article URLs.
- Hacker News chrome rows like `Hacker News`, `Apply to YC`, and timestamp-only rows are filtered as listing utility noise.
- Reddit static verification title is classified as a blocked challenge page.
- Reddit rendered thread bodies using `[slot='text-body']` / `.md` now populate `forum_detail.content`.

## Final Verification

Focused tests:

```text
255 passed, 12 skipped, 11 warnings
```

Command:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_article_forum_live_regressions.py tests/services/test_content_article_forum_surfaces.py tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_listing_identity_regressions.py tests/services/test_listing_integrity_gate.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_detail_extractor_structured_sources.py -q
```

Extended live smoke:

```text
article_forum_surfaces_extended: 10 ok / 0 failed
```

Command:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_extraction_smoke.py --corpus artifacts/article_forum_surface_extended_corpus.json --groups article_forum_surfaces_extended --timeout 90
```

Final data audit:

- MDN docs: clean, `content_len=9894`
- Django docs: clean, `content_len=9672`
- Node docs: clean, `content_len=3589`
- Wikipedia GDP table: clean, 20 records
- Hacker News: clean story rows; chrome rows filtered
- GitHub Blog index: clean, 10 records
- GitHub Blog article: clean, `content_len=9891`, `publication_date=2025-06-16`
- MDN Blog article: clean, `content_len=7947`, `publication_date=January 24, 2025`
- Stack Overflow: clean, `content_len=74236`
- Reddit: clean, `content_len=2867`

Remaining note:

- Stack Overflow and Reddit can use browser path and are slower than static pages. Correctness passed; performance tuning is separate.
- Test runs still print the existing local default-secret warning. Not related to extraction.
