from __future__ import annotations

from app.extraction import (
    extract,
    parse_surface,
)
from app.extraction.contracts import ExtractionResult

from app.extraction.replay import request_from_acquisition_result


def extract_records_for_acquisition_result(
    acquisition_result,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str,
    requested_fields: list[str] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
) -> ExtractionResult:
    normalized_surface = parse_surface(surface)
    request = request_from_acquisition_result(
        normalized_surface,
        acquisition_result,
        requested_url=requested_page_url,
        max_records=max_records,
        requested_fields=tuple(str(field) for field in requested_fields or ()),
        selector_rules=selector_rules,
    )
    return extract(request)
