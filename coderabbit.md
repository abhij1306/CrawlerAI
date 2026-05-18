Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/main.py around lines 177 - 183, The function _is_trusted_proxy builds a set from crawler_runtime_settings.api_rate_limit_trusted_proxies on every call; move that one-time computation to module-level (e.g., compute a TRUSTED_PROXIES set at import time from crawler_runtime_settings.api_rate_limit_trusted_proxies with str(...).strip() filtering) and change _is_trusted_proxy(proxy_ip: str) to simply return proxy_ip in TRUSTED_PROXIES; if settings can change at runtime, expose a small helper to refresh the module-level set and call it when settings are updated.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/ucp_audit/compliance_checks.py around lines 81 - 85, The scoring formula in _variant_score uses a hardcoded 3 as the metric count which makes the result brittle; change _variant_score to compute metric_count dynamically (e.g., build a list of the metrics [collapsed, sku, availability] or derive it from _variant_findings and count non-zero/active metrics) and use total * metric_count as the denominator (guarding against metric_count == 0) so adding/removing metrics won’t silently break the calculation.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/api/ucp_audit.py around lines 76 - 107, The export endpoints currently call build_ucp_audit_job_payload which loads the full job + page results even though export_json and export_markdown only need the report; add a new helper get_ucp_audit_report(session: AsyncSession, job_id: int) that does a lightweight session.scalar(select(UCPAuditReport).where(UCPAuditReport.job_id == job_id)) to fetch only the report, then update export_json and export_markdown to first validate the job/permissions via get_ucp_audit_job(job_id, session, user) (to preserve auth and 404 behavior) and then call get_ucp_audit_report(session, job_id); if it returns None raise the same 404, otherwise return the response using report.report_json or report.markdown_report respectively.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/models/ucp_audit.py around lines 51 - 52, The url and acquisition_mode mapped columns currently supply empty-string defaults which can mask missing data; update the UcpAudit model by removing the default="" arguments from the mapped_column calls for url and acquisition_mode (or alternatively set nullable=True or replace with a meaningful default like "unknown" if you prefer), ensuring the mapped_column declarations for url and acquisition_mode require explicit values on object creation (keep or set nullable=False to preserve NOT NULL if you want DB enforcement). Use the identifiers url and acquisition_mode in ucp_audit.py and adjust any constructors or factory code that creates UcpAudit instances to pass explicit values.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/ucp_audit/reporting.py around lines 20 - 44, The build_markdown_report function currently interpolates unescaped fields (report.domain, report.audit_id, report.overall_score, report.d_ucp1_gate_applied, dimension.dimension_id, dimension.score, dimension.status, finding.dimension_id, finding.code, finding.severity, finding.message) into markdown and should escape markdown special characters first; add a small helper (e.g., escape_markdown) that escapes characters like `\`*_{}[]()#+-.!` and call it when formatting each interpolated value in build_markdown_report so every inserted value (especially report.domain, dimension.dimension_id, finding.code and finding.message) is passed through escape_markdown before being appended to lines.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/ucp_audit/test_reporting.py around lines 15 - 44, The test_data in test_report_payload_contains_summary_scores_and_findings is inconsistent: dimension_scores[0] includes a UCPFinding ("manifest_missing") but the UCPComplianceReport instance sets all_findings = [], so update the test to be explicit about expected behavior — either populate all_findings with the same finding(s) from dimension_scores (e.g., include the UCPFinding in all_findings) or, if build_report_payload is supposed to derive all_findings from dimension_scores, add an assertion that payload["all_findings"] contains the "manifest_missing" finding; locate the test function name test_report_payload_contains_summary_scores_and_findings, the UCPComplianceReport instantiation, the all_findings field, and the call to build_report_payload to make the appropriate change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/ucp-audit/ucp-audit-components.tsx around lines 154 - 174, The list of selectable jobs uses a <button> with aria-pressed (in the map rendering each job, referencing job.id, activeId, onSelect) which is better expressed with a single-selection widget; update the container that renders these buttons to use a semantic pattern (either a radiogroup or listbox) and adjust each item: for the radio pattern wrap with role="radiogroup" and change each job item to role="radio" with aria-checked={job.id === activeId}, or for the listbox pattern wrap with role="listbox" and change each job item to role="option" with aria-selected={job.id === activeId}; keep the existing onClick/onSelect behavior and visual styling (cn, Badge, badgeTone, ExternalLink) but replace aria-pressed with the appropriate aria-* attribute and add keyboard/select handling consistent with the chosen pattern.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/ucp-audit/use-ucp-audit.ts around lines 18 - 40, The jobs list polling in useUcpAudit is currently hardcoded to 4000ms (jobsQuery.refetchInterval) which may be too aggressive; make the interval configurable by adding a jobsPollInterval field to UcpAuditOptions/defaultOptions (e.g., default 5000 or 10000) and replace the literal 4000 in the jobsQuery refetchInterval with options.jobsPollInterval, ensuring callers can update setOptions or pass a different value via options so polling can be tuned or disabled in environments where 4s is too frequent.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: The default report-format list is narrower than the audit pipeline's expected format contract.
   Path: backend/app/services/config/ucp_audit.py
   Lines: 24-24

2. logic error: An invalid regex timeout now suppresses all matches instead of falling back to no timeout.
   Path: backend/app/services/dom/xpath_service.py
   Lines: 204-204

3. possible bug: Re-exporting a private URL-to-title helper can break the title-hint contract used by long-text sanitization.
   Path: backend/app/services/extract/detail/assembly/final_cleanup.py
   Lines: 60-60

4. logic error: Numeric variant prices can be overwritten because distinctness is detected using text coercion.
   Path: backend/app/services/extract/variant_normalization/backfill.py
   Lines: 152-152

5. possible bug: Eagerly importing sibling normalization modules can break startup with circular-import issues.
   Path: backend/app/services/extract/variant_normalization/common.py
   Lines: 8-8

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.