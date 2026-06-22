from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ArtifactReference(FrozenModel):
    name: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str
    size_bytes: int = Field(ge=0)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ValueError("sha256 must be 64 hexadecimal characters")
        return normalized


class AttemptArtifactSet(FrozenModel):
    attempt_id: str = Field(min_length=1)
    artifacts: tuple[ArtifactReference, ...] = ()


class ExtractionArtifactSet(FrozenModel):
    artifacts: tuple[ArtifactReference, ...] = ()


class ArtifactManifest(FrozenModel):
    schema_version: Literal["artifact-manifest.v1"] = "artifact-manifest.v1"
    run_id: int
    url_result_id: int
    bundle_id: str = Field(min_length=1)
    attempts: tuple[AttemptArtifactSet, ...] = ()
    extraction: ExtractionArtifactSet
    redaction_policy_version: str = "1"
