from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.acquisition.contracts import AcquisitionPlan, AttemptSpec


class PlanningRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    mode: Literal["auto", "http_only", "browser_only", "http_then_browser"] = "auto"
    deadline: datetime
    proxy: str | None = None
    required_artifacts: tuple[str, ...] = ()
    traversal_mode: str | None = None
    warmup: bool = False
    interaction: bool = False


class AcquisitionPlanner:
    policy_version = "1"

    def plan(self, request: PlanningRequest) -> AcquisitionPlan:
        created_at = datetime.now(UTC)
        transports = self._transports(request.mode)
        remaining = max(0.001, (request.deadline - created_at).total_seconds())
        timeout = max(0.001, remaining / max(1, len(transports)))
        plan_key = f"{request.url}|{request.surface}|{created_at.isoformat()}"
        plan_id = sha256(plan_key.encode("utf-8")).hexdigest()[:20]
        attempts = tuple(
            AttemptSpec(
                attempt_id=f"{plan_id}-{index}-{transport}",
                transport=transport,
                proxy=request.proxy,
                warmup=request.warmup and transport in {"patchright", "real_chrome"},
                interaction=request.interaction and transport in {"patchright", "real_chrome"},
                traversal_mode=request.traversal_mode,
                required_artifacts=request.required_artifacts,
                timeout_seconds=timeout,
                reason=self._reason(index, transport),
            )
            for index, transport in enumerate(transports, start=1)
        )
        return AcquisitionPlan(
            plan_id=plan_id,
            attempts=attempts,
            created_at=created_at,
            deadline=request.deadline,
            policy_version=self.policy_version,
        )

    @staticmethod
    def _transports(mode: str) -> tuple[str, ...]:
        if mode == "http_only":
            return ("curl", "httpx")
        if mode == "browser_only":
            return ("patchright", "real_chrome")
        return ("curl", "httpx", "patchright", "real_chrome")

    @staticmethod
    def _reason(index: int, transport: str) -> str:
        return "initial_http" if index == 1 and transport == "curl" else f"fallback_{transport}"
