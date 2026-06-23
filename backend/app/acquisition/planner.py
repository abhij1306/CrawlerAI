from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.acquisition.contracts import AcquisitionPlan, AttemptSpec

Transport = Literal["curl", "httpx", "patchright", "real_chrome"]


class PlanningRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    mode: Literal["auto", "http_only", "browser_only", "http_then_browser"] = "auto"
    deadline: datetime
    proxy: str | None = None
    proxies: tuple[str | None, ...] = ()
    force_httpx: bool = False
    required_artifacts: tuple[str, ...] = ()
    traversal_mode: str | None = None
    warmup: bool = False
    interaction: bool = False


class AcquisitionPlanner:
    policy_version = "1"

    def plan(self, request: PlanningRequest) -> AcquisitionPlan:
        created_at = datetime.now(UTC)
        transports = self._transports(request.mode, force_httpx=request.force_httpx)
        proxies = self._proxies(request)
        remaining = max(0.001, (request.deadline - created_at).total_seconds())
        plan_key = f"{request.url}|{request.surface}|{created_at.isoformat()}"
        plan_id = sha256(plan_key.encode("utf-8")).hexdigest()[:20]
        attempt_inputs = tuple(
            (transport, proxy) for transport in transports for proxy in proxies
        )
        attempts = tuple(
            AttemptSpec(
                attempt_id=f"{plan_id}-{index}-{transport}",
                transport=transport,
                proxy=proxy,
                warmup=request.warmup and transport in {"patchright", "real_chrome"},
                interaction=request.interaction
                and transport in {"patchright", "real_chrome"},
                traversal_mode=request.traversal_mode,
                required_artifacts=request.required_artifacts,
                timeout_seconds=remaining,
                reason=self._reason(index, transport),
            )
            for index, (transport, proxy) in enumerate(attempt_inputs, start=1)
        )
        return AcquisitionPlan(
            plan_id=plan_id,
            attempts=attempts,
            created_at=created_at,
            deadline=request.deadline,
            policy_version=self.policy_version,
        )

    @staticmethod
    def _transports(mode: str, *, force_httpx: bool = False) -> tuple[Transport, ...]:
        if mode == "http_only":
            return ("httpx",) if force_httpx else ("curl", "httpx")
        if mode == "browser_only":
            return ("patchright", "real_chrome")
        http_transports = ("httpx",) if force_httpx else ("curl", "httpx")
        return (*http_transports, "patchright", "real_chrome")

    @staticmethod
    def _proxies(request: PlanningRequest) -> tuple[str | None, ...]:
        candidates = request.proxies or (request.proxy,)
        resolved: list[str | None] = []
        for candidate in candidates:
            normalized = str(candidate).strip() if candidate is not None else None
            normalized = normalized or None
            if normalized not in resolved:
                resolved.append(normalized)
        return tuple(resolved or [None])

    @staticmethod
    def _reason(index: int, transport: str) -> str:
        return (
            "initial_http"
            if index == 1 and transport == "curl"
            else f"fallback_{transport}"
        )
