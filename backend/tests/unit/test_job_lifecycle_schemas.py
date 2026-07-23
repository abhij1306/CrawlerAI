"""Shared job-lifecycle schema bases (audit 3.11).

Pins the PI ≡ DE contract: all nine job-response fields live on
``BaseJobResponse`` (base-then-subclass field order keeps the serialized JSON
identical), the create shapes share ``BaseJobCreate``/``BaseSourceRecordInput``
with per-subclass options narrowing, and ``ProductIntelligenceDiscoveryRequest``
no longer re-declares the create shape inline.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.data_enrichment import (
    DataEnrichmentJobCreate,
    DataEnrichmentJobResponse,
    DataEnrichmentOptions,
    DataEnrichmentSourceRecordInput,
)
from app.schemas.job_lifecycle import (
    BaseJobCreate,
    BaseJobResponse,
    BaseSourceRecordInput,
)
from app.schemas.product_intelligence import (
    ProductIntelligenceDiscoveryRequest,
    ProductIntelligenceJobCreate,
    ProductIntelligenceJobResponse,
    ProductIntelligenceOptions,
    ProductIntelligenceSourceRecordInput,
)

pytestmark = pytest.mark.unit

_JOB_RESPONSE_FIELDS = [
    "id",
    "user_id",
    "source_run_id",
    "status",
    "options",
    "summary",
    "created_at",
    "updated_at",
    "completed_at",
]


class _JobRow:
    id = 7
    user_id = 3
    source_run_id = 11
    status = "running"
    options = {"a": 1}
    summary = {"b": 2}
    created_at = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    completed_at = None


def test_job_response_fields_live_on_the_base_in_order() -> None:
    assert list(BaseJobResponse.model_fields) == _JOB_RESPONSE_FIELDS
    assert list(ProductIntelligenceJobResponse.model_fields) == _JOB_RESPONSE_FIELDS
    assert list(DataEnrichmentJobResponse.model_fields) == _JOB_RESPONSE_FIELDS


def test_job_response_serialization_is_byte_identical_across_providers() -> None:
    pi_json = ProductIntelligenceJobResponse.model_validate(_JobRow()).model_dump_json()
    de_json = DataEnrichmentJobResponse.model_validate(_JobRow()).model_dump_json()
    assert pi_json == de_json
    assert pi_json == (
        '{"id":7,"user_id":3,"source_run_id":11,"status":"running",'
        '"options":{"a":1},"summary":{"b":2},'
        '"created_at":"2026-07-01T12:00:00Z",'
        '"updated_at":"2026-07-02T12:00:00Z","completed_at":null}'
    )


def test_source_record_inputs_share_the_base_shape() -> None:
    assert list(BaseSourceRecordInput.model_fields) == [
        "id",
        "run_id",
        "source_url",
        "data",
    ]
    assert list(ProductIntelligenceSourceRecordInput.model_fields) == list(
        DataEnrichmentSourceRecordInput.model_fields
    )
    row = ProductIntelligenceSourceRecordInput.model_validate(
        {"id": 1, "source_url": "https://example.com/p/1", "data": {"k": "v"}}
    )
    assert row.model_dump() == {
        "id": 1,
        "run_id": None,
        "source_url": "https://example.com/p/1",
        "data": {"k": "v"},
    }


def test_job_create_shape_shared_with_per_subclass_options() -> None:
    assert list(BaseJobCreate.model_fields) == [
        "source_run_id",
        "source_record_ids",
        "source_records",
        "options",
    ]
    pi = ProductIntelligenceJobCreate.model_validate(
        {"source_run_id": 5, "options": {"max_source_products": 3}}
    )
    assert isinstance(pi.options, ProductIntelligenceOptions)
    assert pi.options.max_source_products == 3
    de = DataEnrichmentJobCreate.model_validate(
        {"options": {"max_source_records": 9, "llm_enabled": True}}
    )
    assert isinstance(de.options, DataEnrichmentOptions)
    assert de.options.max_source_records == 9
    with pytest.raises(ValueError):
        DataEnrichmentJobCreate.model_validate({"options": {"max_source_records": 0}})


def test_discovery_request_reuses_the_job_create_shape() -> None:
    assert list(ProductIntelligenceDiscoveryRequest.model_fields) == list(
        ProductIntelligenceJobCreate.model_fields
    )
    parsed = ProductIntelligenceDiscoveryRequest.model_validate(
        {"source_records": [{"run_id": 2}], "options": {"private_label_mode": "flag"}}
    )
    assert isinstance(parsed.options, ProductIntelligenceOptions)
    assert isinstance(parsed.source_records[0], ProductIntelligenceSourceRecordInput)
    assert parsed.options.private_label_mode == "flag"
