Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/dom_runtime.py around lines 146 - 169, The shadow DOM flattening diagnostics payload is inconsistent across exit paths because `max_hosts` and `errors` are only present in the exception return and omitted from the `max_hosts <= 0` and non-dict fallback cases. Update the return handling around the `result` dict and the `page.evaluate`/`raw` validation so every branch returns the same completeness schema, including `max_hosts`, `errors`, `shadow_roots_detected`, `shadow_roots_flattened`, `closed_shadow_roots_detected`, `hidden_panel_dom_present`, and `serialization_method_version`.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/collectors/dom.py around lines 336 - 354, The token allow/deny logic in _hidden_product_content_allowed currently uses raw substring checks against the concatenated context, which can match unrelated words. Update the matching to be token-aware or boundary-aware by normalizing and splitting the collected attributes from the node and its ancestors before comparing against DETAIL_HIDDEN_PRODUCT_CONTENT_NEGATIVE_TOKENS and DETAIL_HIDDEN_PRODUCT_CONTENT_POSITIVE_TOKENS, so only whole tokens or intended phrases influence the result.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/collectors/js_state.py at line 739, The variant asset group_id in the js_state collector is colliding because it only uses the per-key index, so different image-related keys can produce the same identifier. Update the group_id construction in the variant asset handling logic to include the source key name as well as the index, using the existing artifact_id, path, and the relevant key variable in this collector so each distinct URL gets its own unique group_id.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/resolution.py around lines 1962 - 1964, The brand resolution path in resolution.py is allowing invalid rejected candidates to trigger page identity replacement even when existing_brand is already resolved. Update the logic around allow_page_identity_replacement in the brand candidate handling so that _brand_from_title can only replace with page identity when there is no resolved existing_brand, and keep the existing resolved brand untouched otherwise.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/validation.py around lines 548 - 568, The offer-group filtering in validation should not skip groups just because they contain an OfferEntity; linked_group_ids in validate/join logic currently treats every offer as linked, which suppresses child-join failures. Update the group check in the evidence validation flow to only exclude groups that actually have a variant-linked offer (for example, use the offer’s variant_entity_id or equivalent join-link field), while keeping unvariant-linked offer groups so the existing join validation can emit the missing-child finding.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/observability/run_report.py around lines 215 - 218, The _string_list helper is dropping falsy-but-valid values because it applies item or "" before string conversion. Update _string_list in run_report.py to convert each list/tuple item to a string once, then filter on the stripped result, so values like 0 or False are preserved if they stringify to non-empty text.