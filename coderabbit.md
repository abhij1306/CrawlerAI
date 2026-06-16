Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce.py around lines 183 - 189, Remove the local definition of the ALL_CANONICAL_FIELDS constant (the dead code around lines 136-143) since it is now shadowed by the import of ALL_CANONICAL_FIELDS from field_surface on line 184. Delete the entire local definition to eliminate the code duplication and ensure the imported version is used throughout the file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/candidate_materialization.py around lines 23 - 34, The source_rank parameter in the winning_materialized_field function lacks a type annotation, which reduces code clarity and IDE support. Add an appropriate type annotation to the source_rank parameter. Based on its usage in the function where it is called as a lambda that accepts surface, field_name, and source arguments, it should be typed as a callable that takes these three parameters and returns a value suitable for ordering/ranking candidates.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce_dispatch.py around lines 40 - 53, The circular import between field_coerce_dispatch.py and field_coerce.py must be resolved. Create a new shared base module (e.g., field_coerce_base.py) and move the imported helpers (_coerce_structured_multi_rows, coerce_structured_scalar, coerce_location, salary_from_json, coerce_product_attributes, _sanitize_option_scalar, _color_value_is_opaque_code) and constants (RATING_RE, _AVAILABILITY_CANONICAL_ENUM, _product_type_noise_tokens, _PRICE_FIELD_NAMES, _INTEGER_FIELD_NAMES) into this new base module. Then update both field_coerce.py and field_coerce_dispatch.py to import these items from the new base module instead of from each other.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_surface.py around lines 142 - 169, In the surface_alias_lookup function, the if block checking both normalized_requested and exact_field (lines 156-157) is redundant because the earlier if block (lines 152-153) already assigns lookup[normalized_requested] = exact_field when exact_field is truthy (since exact_field or normalized_requested evaluates to exact_field in that case). Remove the redundant if block that checks the combined condition of normalized_requested and exact_field together.