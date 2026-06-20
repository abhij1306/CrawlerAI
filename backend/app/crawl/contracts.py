from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


Verdict = Literal[
    "success",
    "partial",
    "review",
    "invalid",
    "empty",
    "blocked",
    "error",
    "wrong_surface",
]


class UrlResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["url-result.v1"] = "url-result.v1"
    run_id: int
    url_result_id: int | None = None
    generation: int = Field(default=1, ge=1)
    requested_url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    acquisition_outcome: Literal["success", "blocked", "empty", "error"]
    extraction_verdict: Verdict
    bundle_id: str | None = None
    manifest_uri: str | None = None
    record_ids: tuple[int, ...] = ()
    error: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        return self.extraction_verdict


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["run-summary.v1"] = "run-summary.v1"
    url_count: int = 0
    record_count: int = 0
    verdict_counts: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_results(cls, results: tuple[UrlResult, ...]) -> "RunSummary":
        verdict_counts = Counter(result.verdict for result in results)
        return cls(
            url_count=len(results),
            record_count=sum(len(result.record_ids) for result in results),
            verdict_counts=dict(sorted(verdict_counts.items())),
        )
