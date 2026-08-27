# CrawlerAI Business Logic

Stable user-visible behavior. Implementation detail belongs in architecture docs; hard constraints
belong in `INVARIANTS.md`.

## Runs and controls

- The user-selected surface is authoritative. CrawlerAI never silently turns listing work into detail work or changes traversal, proxy, diagnostics, or LLM intent.
- Quick and Advanced are two presentations of the same backend settings contract. Explicit user edits override saved defaults for that run.
- A run freezes the runtime/profile/extraction configuration needed for reproducible execution. Later configuration changes affect future runs.
- Single URLs, bulk input, CSV input, and discovered category URLs enter the same per-URL crawl pipeline.
- Category discovery returns candidate same-origin URLs. Selected URLs become normal batch inputs; discovery does not create records itself.
- `max_records` is a traversal stop target, not a post-extraction database cap.
- Pause, resume, kill, progress, logs, records, review, and exports remain scoped to the requesting user.
- Acceptance/evaluation preserves the declared surface and checks record quality, identity, and integrity; a `success` verdict alone is insufficient.

## Acquisition

- CrawlerAI starts with the configured deterministic acquisition policy and escalates only when observed content, block/shell evidence, learned policy, and remaining budget justify it.
- Explicit fetch mode and robots policy are authoritative. The shared HTTP waterfall is bounded; traversal is separate from render escalation.
- Browser use improves observation. It does not assign product fields.
- Traversal runs only when the user enabled it. Listing discovery and detail expansion stay bounded and visible in diagnostics.
- A usable rendered page wins over vendor-marker noise. Genuine challenge/error shells remain failures or partial observations.
- Screenshots, network capture, and other diagnostic artifacts follow explicit run controls.
- Every browser attempt returns bounded method, engine, readiness, block, timing, and artifact diagnostics, including failures.
- Successful acquisition paths may update reusable `(domain, surface)` execution profiles. Explicit settings always override memory; stale memory stops forcing old choices.
- Browser cookies and storage are isolated by user/run/domain/engine as applicable. State from blocked challenges is not reusable success memory.

## Extraction and output

- Deterministic extraction is primary. Evidence is collected from adapters, structured sources, network/JS state, and DOM, then resolved before publication.
- Listing output contains product rows. Zero valid rows produce `listing_detection_failed`, never a fake one-row page summary.
- Listing readiness requires listing evidence. A standalone structured Product, page metadata, or job-search hub is not a listing row. Listing fields stay card-scoped.
- Detail output represents the requested product. Category pages, sibling products, recommendations, ads, and site chrome cannot become the canonical product.
- Detail routing rejects utility-page redirects and collection paths. Same-site cross-subdomain product links are allowed only when product identity remains credible.
- Requested fields remain part of the extraction contract. Missing or conflicting fields stay visible through field state, findings, and diagnostics.
- Requested labels are matched exactly before aliases. Common accordion/section labels are resolved during extraction, and detail tables remain scoped to the requested product.
- Transport success and data quality are separate. A 2xx page can still produce partial, failed, or suppressed output.
- Product variants are flat public rows with stable identity, public axes, and offer fields. Internal variant helpers never leak to API or export output.
- Publication and persistence serialize resolved facts. They do not repair extraction mistakes.
- Records expose bounded provenance and diagnostics sufficient to explain selected, rejected, conflicting, missing, or unavailable values.
- Cleaned DOM may aid extraction, but original acquisition evidence and provenance remain available. Page context is internal and content-first.
- Record identity is stable within a run; duplicate observations do not create duplicate public products.

## Review and memory

- Operators review persisted crawl results; review does not rewrite the historical run.
- Keep/reject feedback and selector changes affect future runs through extraction memory.
- Completed-run promotion is the normal recipe-learning workflow. Selector self-heal runs only for unresolved requested fields and persists only validated improvements.
- Extraction releases are immutable for in-flight runs. Operator changes create future behavior, not mid-run drift.
- Selector/recipe memory is scoped by normalized domain and surface. Acquisition profiles and cookie memory remain separate concerns.
- Learned recipes store reusable locators, paths, endpoint families, and validation rules—not previously extracted product values.

## LLM behavior

- LLM use requires both run intent and active provider configuration.
- Deterministic evidence remains authoritative.
- Ecommerce-detail LLM is evidence adjudication only. It may select/reject grounded evidence, suggest reusable locators, or abstain; it does not invent missing product values.
- LLM failures degrade visibly and do not corrupt deterministic state.

## Ecommerce-detail public fields

- The detail record publishes `rating`, `review_count`, `materials`, `gender`,
  `condition`, `style_id`, and `barcode` alongside the existing commercial fields.
  Each is published only from source evidence and carries lineage; none is inferred
  to fill a gap.
- `barcode` is the public name for a product's GTIN/UPC/EAN.
  A source-declared GTIN with the public digit length remains source evidence
  when its checksum fails; checksum failure is diagnostic and lowers candidate
  rank, but does not erase the role the source declared. Values outside the
  supported 8/12/13/14-digit shape cannot publish as barcodes.
- `style_id` is the family/style identifier (schema.org `productGroupID`) and stays
  distinct from `sku`, which is the product-level merchant SKU.
- `gender` states the audience the source declares, either structurally or in the
  requested PDP path; it is never inferred from query or tracking state.
- schema.org enumerations publish as plain wording (`NewCondition` becomes `New`).
- A condition stated by a product publishes directly. A condition stated only
  by offers publishes at product level only when every stated product offer
  agrees; conflicting offer conditions remain missing.
- Trademark and service-mark symbols are legal notation and are not part of a
  published title or brand.
- `title` is the selected target's source-declared semantic product name, not a
  title assembled from separate brand, colour, size, gender, condition, or
  identifier fields. A target-confirmed structured `Product`/`ProductGroup`
  name is authoritative; when that is absent or ambiguous, resolution falls
  back to the product's visible heading, dedicated product metadata/document
  title, and finally the requested product URL. Source spelling, case, and
  punctuation are preserved apart from documented whitespace, legal-symbol,
  and site-boilerplate cleanup. Competing source titles remain evidence even
  though the scalar publication selects one.
- `brand` prefers an explicit target-scoped manufacturer, designer,
  private-label, or vendor value. Its source spelling, case, and punctuation
  are preserved apart from legal-symbol cleanup. Page identity, title, or URL
  derivation is allowed only when no valid explicit product brand exists and
  independent source signals identify one unambiguously; a derived brand never
  replaces an explicit one.
- `rating` publishes as a decimal and `review_count` as an integer, the types the
  canonical record declares. The conversion from source text is an authorized
  canonicalization carrying its own lineage. `price` stays a string, where
  trailing-zero precision is part of the value.
- A URL-less schema Product may bind to the requested product through its sole
  Offer URL when that URL names the same product resource. The URL is ownership
  evidence only; it is not copied into a product identifier field.
- A page that fails acquisition (an anti-automation shell) publishes no product
  rather than a value derived from the URL.

## Enrichment and product intelligence

- Enrichment is on-demand and separate from crawl output. It reads successful ecommerce-detail records and writes derived enrichment rows.
- Enrichment never cleans polluted extraction fields; extraction defects are fixed upstream.
- Product Intelligence discovers candidate product URLs, scores deterministic identity evidence, and presents matches for review.
- Exact product identifiers outrank titles. Color/size differences do not automatically mean a different model.
- Product Intelligence does not create monitors or alerts. Selected URLs return to normal crawl workflows.

## Public API and MCP

- API keys authenticate `/api/v1`; global/IP limits run before key lookup and per-key limits after authentication.
- Public single-product extraction uses the normal crawl/extraction contracts with its documented HTTP-only limits. It does not start hidden browser, traversal, worker, screenshot, network-capture, or LLM work.
- Deferred batch requests report worker requirements rather than pretending synchronous completion.
- MCP calls the public REST API with a principal API key. It is local/stdio by default and does not bypass authentication or rate limits.

## Verdicts and artifacts

- Run status describes orchestration. URL verdict and data integrity describe extraction outcome. Neither substitutes for the other.
- Mixed-result runs preserve successful records and diagnostics for failed URLs.
- Each URL result owns one public record artifact and one self-contained diagnosis alongside acquired HTML. Run reports group those diagnoses.
- Exports use the same authorized public record contract as records APIs.

Update this file only when user-visible semantics change. File moves, refactors, thresholds, and
implementation mechanics belong elsewhere.
