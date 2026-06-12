from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import logging
from typing import Any, cast

import httpx
from app.services.acquisition_plan import AcquisitionPlan
from app.services.acquisition.policy import AcquisitionPolicy
from app.services.acquisition.policy_middleware import PolicyMiddleware
from app.services.acquisition.internal_api_replay import replay_internal_api_endpoints
from app.services.adapters.registry import normalize_adapter_acquisition_url
from app.services.config.domain_profiles import INTERNAL_API_ENDPOINTS_PROFILE_KEY
from app.services.crawl.utils import normalize_target_url
from app.services.fetch.fetch_context import fetch_page
from app.services.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AcquisitionRequest:
    run_id: int
    url: str
    plan: AcquisitionPlan
    requested_fields: list[str] = field(default_factory=list)
    requested_field_selectors: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    acquisition_profile: dict[str, object] = field(default_factory=dict)
    policy: AcquisitionPolicy | None = None
    checkpoint: Any = None
    on_event: Any = None

    def __post_init__(self) -> None:
        policy = self.policy or AcquisitionPolicy.from_profile(self.acquisition_profile)
        self.policy = policy
        if not self.acquisition_profile:
            self.acquisition_profile = policy.to_profile()

    def with_profile_updates(self, **updates: object) -> "AcquisitionRequest":
        policy = (
            self.policy or AcquisitionPolicy.from_profile(self.acquisition_profile)
        ).with_updates(**cast(Any, updates))
        profile = policy.to_profile()
        return replace(self, acquisition_profile=profile, policy=policy)

    @property
    def surface(self) -> str:
        return self.plan.surface

    @property
    def proxy_list(self) -> list[str]:
        return list(self.plan.proxy_list)

    @property
    def traversal_mode(self) -> str | None:
        return self.plan.traversal_mode

    @property
    def max_pages(self) -> int:
        return self.plan.max_pages

    @property
    def max_scrolls(self) -> int:
        return self.plan.max_scrolls

    @property
    def max_records(self) -> int:
        return self.plan.max_records


@dataclass(slots=True)
class AcquisitionResult:
    request: AcquisitionRequest
    final_url: str
    html: str
    method: str
    status_code: int
    content_type: str = "text/html"
    blocked: bool = False
    platform_family: str | None = None
    json_data: dict[str, object] | list[object] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    adapter_records: list[dict[str, object]] = field(default_factory=list)
    adapter_name: str | None = None
    adapter_source_type: str | None = None
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PageEvidence:
    blocked: bool
    method: str
    diagnostics: dict[str, object]

    @classmethod
    def from_acquisition_result(
        cls, acquisition_result: AcquisitionResult
    ) -> "PageEvidence":
        diagnostics = getattr(acquisition_result, "browser_diagnostics", {})
        return cls(
            blocked=bool(getattr(acquisition_result, "blocked", False)),
            method=str(getattr(acquisition_result, "method", "") or ""),
            diagnostics=dict(diagnostics or {})
            if isinstance(diagnostics, dict)
            else {},
        )

    @classmethod
    def from_browser_diagnostics(
        cls, diagnostics: dict[str, object] | object
    ) -> "PageEvidence":
        payload = dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}
        return cls(blocked=False, method="", diagnostics=payload)

    @property
    def browser_attempted(self) -> bool:
        return (
            bool(self.diagnostics.get("browser_attempted")) or self.method == "browser"
        )

    @property
    def browser_outcome(self) -> str:
        return str(self.diagnostics.get("browser_outcome") or "").strip().lower()

    @property
    def browser_reason(self) -> str:
        return str(self.diagnostics.get("browser_reason") or "").strip().lower()

    @property
    def challenge_evidence(self) -> list[str]:
        return [
            str(item or "").strip().lower()
            for item in _list_or_empty(self.diagnostics.get("challenge_evidence"))
            if str(item or "").strip()
        ]

    @property
    def has_ready_readiness_probe(self) -> bool:
        return any(
            isinstance(probe, dict) and bool(probe.get("is_ready"))
            for probe in _list_or_empty(self.diagnostics.get("readiness_probes"))
        )

    @property
    def indicates_block(self) -> bool:
        if self.blocked or self.browser_outcome == "challenge_page":
            return True
        if any(
            item.startswith(("title:", "strong:")) for item in self.challenge_evidence
        ):
            return True
        if self.browser_outcome == "usable_content" and self.has_ready_readiness_probe:
            return False
        # INVARIANTS.md Rule 6: usable content beats provider noise.
        if self.browser_outcome == "usable_content":
            return False
        provider_evidence = _list_or_empty(
            self.diagnostics.get("challenge_provider_hits")
        ) or [
            item
            for item in self.challenge_evidence
            if item.startswith(("provider:", "active_provider:"))
        ]
        return bool(provider_evidence and self.browser_outcome != "usable_content")

    @property
    def challenge_shell_reason(self) -> str | None:
        if self.browser_outcome == "usable_content" and not self.indicates_block:
            return None
        challenge_shell = (
            self.browser_outcome in {"challenge_page", "low_content_shell"}
            or self.indicates_block
            or (
                self.browser_reason.startswith("vendor-block:")
                and not self.has_ready_readiness_probe
            )
        )
        return "challenge_shell" if challenge_shell else None


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


async def _emit_event(on_event: Any, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.exception(
            "Acquisition event callback failed",
            extra={"event_level": level, "event_message": message},
        )
        return


async def acquire(request: AcquisitionRequest) -> AcquisitionResult:
    requested_url = normalize_target_url(request.url)
    effective_url = (
        await normalize_adapter_acquisition_url(requested_url) or requested_url
    )
    runtime_policy = resolve_platform_runtime_policy(
        effective_url,
        surface=request.surface,
    )
    acquisition_policy = _apply_runtime_policy_defaults(
        _resolve_acquisition_policy(request),
        runtime_policy=runtime_policy,
    ).with_platform_requirements(
        requires_browser=bool(runtime_policy.get("requires_browser")),
    )
    browser_reason = acquisition_policy.browser_reason
    if browser_reason is None and bool(runtime_policy.get("requires_browser")):
        browser_reason = "platform-required"
    policy_middleware = PolicyMiddleware()
    await policy_middleware.before_fetch(request)
    request = request.with_profile_updates(**acquisition_policy.to_profile())
    await _emit_event(request.on_event, "info", f"Acquiring {effective_url}")
    profile_endpoints = request.acquisition_profile.get(
        INTERNAL_API_ENDPOINTS_PROFILE_KEY
    )
    replay_payload = await replay_internal_api_endpoints(
        page_url=effective_url,
        surface=request.surface,
        endpoints=profile_endpoints if isinstance(profile_endpoints, list) else [],
        requested_fields=list(request.requested_fields),
    )
    if replay_payload is not None:
        replay_url = str(replay_payload.get("url") or effective_url)
        raw_status = replay_payload.get("status")
        status_code = int(raw_status) if isinstance(raw_status, (int, str)) else 200
        acquisition_result = AcquisitionResult(
            request=request,
            final_url=effective_url,
            html="",
            method="api_replay",
            status_code=status_code,
            content_type=str(
                replay_payload.get("content_type") or "application/json"
            ),
            blocked=False,
            platform_family=runtime_policy.get("family"),
            headers={},
            network_payloads=[replay_payload],
            browser_diagnostics={
                "internal_api_replay": True,
                "internal_api_replay_url": replay_url,
                "network_payload_count": 1,
                "extraction_source": "network_payload_first",
            },
            artifacts={},
        )
        await policy_middleware.after_fetch(acquisition_result)
        return acquisition_result
    result = await fetch_page(
        effective_url,
        run_id=request.run_id,
        proxy_list=request.proxy_list,
        proxy_profile=dict(acquisition_policy.proxy_profile)
        if acquisition_policy.proxy_profile
        else None,
        locality_profile=dict(acquisition_policy.locality_profile)
        if acquisition_policy.locality_profile
        else None,
        fetch_mode=acquisition_policy.fetch_mode,
        prefer_browser=acquisition_policy.prefer_browser,
        surface=request.surface,
        traversal_mode=request.traversal_mode,
        requested_fields=list(request.requested_fields),
        listing_recovery_mode=acquisition_policy.listing_recovery_mode,
        max_pages=request.max_pages,
        max_scrolls=request.max_scrolls,
        max_records=request.max_records,
        browser_reason=browser_reason,
        capture_screenshot=acquisition_policy.capture_screenshot,
        host_memory_ttl_seconds=acquisition_policy.host_memory_ttl_seconds,
        prefer_curl_handoff=acquisition_policy.prefer_curl_handoff,
        handoff_cookie_engine=acquisition_policy.handoff_cookie_engine,
        forced_browser_engine=acquisition_policy.forced_browser_engine,
        on_event=request.on_event,
    )
    acquisition_result = AcquisitionResult(
        request=request,
        final_url=result.final_url,
        html=result.html,
        method=result.method,
        status_code=result.status_code,
        content_type=result.content_type,
        blocked=result.blocked,
        platform_family=getattr(result, "platform_family", None),
        headers=_headers_to_dict(result.headers),
        network_payloads=list(getattr(result, "network_payloads", []) or []),
        browser_diagnostics=dict(getattr(result, "browser_diagnostics", {}) or {}),
        artifacts=dict(getattr(result, "artifacts", {}) or {}),
    )
    await policy_middleware.after_fetch(acquisition_result)
    return acquisition_result


def _merge_context_profiles(
    runtime_context: Mapping[str, object] | None,
    explicit_context: object,
) -> dict[str, object]:
    """Merge browser_context_profile: explicit values override runtime."""
    merged = dict(cast(Mapping[str, object], runtime_context)) if isinstance(runtime_context, Mapping) and runtime_context else {}
    if isinstance(explicit_context, Mapping):
        merged.update(dict(explicit_context))
    return merged


def _merge_locality(
    runtime_locality: Mapping[str, object] | None,
    explicit_locality: dict[str, object],
    *,
    merged_context_profile: dict[str, object],
) -> dict[str, object]:
    """Merge locality: remove browser_context_profile from explicit before merge, inject back."""
    merged = dict(cast(Mapping[str, object], runtime_locality)) if isinstance(runtime_locality, Mapping) and runtime_locality else {}
    explicit_without_context = dict(explicit_locality)
    explicit_without_context.pop("browser_context_profile", None)
    merged.update(explicit_without_context)
    if merged_context_profile:
        merged["browser_context_profile"] = merged_context_profile
    return merged


def _apply_runtime_policy_defaults(
    policy: AcquisitionPolicy,
    *,
    runtime_policy: Mapping[str, object] | None,
) -> AcquisitionPolicy:
    active_policy = dict(runtime_policy or {})
    raw_runtime_locality = active_policy.get("locality_profile")
    raw_runtime_context_profile = active_policy.get("browser_context_profile")
    runtime_locality: Mapping[str, object] | None = (
        raw_runtime_locality
        if isinstance(raw_runtime_locality, Mapping) and raw_runtime_locality
        else None
    )
    runtime_context_profile: Mapping[str, object] | None = (
        raw_runtime_context_profile
        if isinstance(raw_runtime_context_profile, Mapping)
        and raw_runtime_context_profile
        else None
    )
    if runtime_locality is None and runtime_context_profile is None:
        return policy
    explicit_locality = dict(policy.locality_profile)
    merged_context_profile = _merge_context_profiles(
        runtime_context_profile,
        explicit_locality.get("browser_context_profile"),
    )
    merged_locality = _merge_locality(
        runtime_locality,
        explicit_locality,
        merged_context_profile=merged_context_profile,
    )
    if merged_locality == dict(policy.locality_profile):
        return policy
    return policy.with_updates(locality_profile=merged_locality)


def _resolve_acquisition_policy(
    request: AcquisitionRequest,
    *,
    acquisition_profile: Mapping[str, object] | None = None,
) -> AcquisitionPolicy:
    if acquisition_profile is not None:
        return AcquisitionPolicy.from_profile(acquisition_profile)
    return request.policy or AcquisitionPolicy.from_profile(request.acquisition_profile)


def _headers_to_dict(headers: Mapping[str, object] | Any) -> dict[str, str]:
    if isinstance(headers, httpx.Headers):
        return {str(key): str(value) for key, value in headers.items()}
    if isinstance(headers, Mapping):
        return {str(key): str(value) for key, value in headers.items()}
    return {
        str(key): str(value) for key, value in getattr(headers, "items", lambda: [])()
    }
