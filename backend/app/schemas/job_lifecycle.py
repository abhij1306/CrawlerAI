"""Shared job-lifecycle schema bases for source-record job APIs (audit 3.11).

Product intelligence and data enrichment declared byte-identical DTO shapes;
the single owners live here and both schema modules subclass them. All nine
response fields sit on ``BaseJobResponse`` so pydantic's base-then-subclass
field order keeps the serialized JSON identical to the pre-hoist classes.

ORM note (intentionally NOT unified): ``ProductIntelligenceJob.user_id`` is
nullable with ``ondelete=SET_NULL`` (jobs survive user deletion for audit),
while ``DataEnrichmentJob.user_id`` is non-nullable with ``ondelete=CASCADE``.
The schema types both as ``int`` exactly as before — persisting a NULL PI
user_id was already a validation error pre-hoist and stays one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BaseJobResponse(BaseModel):
    """The nine job-response fields PI and DE share verbatim."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    source_run_id: int | None = None
    status: str
    options: dict
    summary: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class BaseSourceRecordInput(BaseModel):
    id: int | None = None
    run_id: int | None = None
    source_url: str = ""
    data: dict = Field(default_factory=dict)


class BaseJobCreate(BaseModel):
    """Shared create shape; subclasses narrow the record/options types.

    ``source_records`` is Sequence-typed at the base (covariant, unlike list)
    so subclasses can narrow the element type; pydantic still validates input
    into a list, so serialization is identical.
    """

    source_run_id: int | None = None
    source_record_ids: list[int] = Field(default_factory=list)
    source_records: Sequence[BaseSourceRecordInput] = Field(default_factory=list)
    options: BaseModel = Field(default_factory=BaseModel)
