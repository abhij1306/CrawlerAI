from __future__ import annotations

import asyncio
from string import Template
from typing import Any

from app.connectors.llm.config_service import (
    load_prompt_file,
    resolve_provider_api_key,
)
from app.connectors.llm.payloads import parse_payload, validate_task_payload
from app.connectors.llm.prompt_rendering import (
    enforce_token_limit,
    stringify_prompt_value,
)
from app.connectors.llm.provider_client import (
    call_provider_with_retry,
    estimate_cost_usd,
)
from app.core.config.evaluation import (
    GENERALIZED_EXTRACTION_BUDGET,
    GENERALIZED_EXTRACTION_FIELD_SENSES,
    GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID,
    GENERALIZED_EXTRACTION_LLM_TASK,
    GENERALIZED_EXTRACTION_PROMPT_REGISTRY,
)
from app.extraction.contracts import (
    ModelEvidenceCandidate,
    UniversalModelArtifact,
    UniversalModelResult,
)
from app.extraction.model_runtime import RuntimeFlatMapPage
from app.extraction.surfaces import listing_schema


class HostedGeneralizedExtractionAdapter:
    adapter_id = GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID

    def __init__(self, *, config_snapshot: dict[str, Any]) -> None:
        self._config = dict(config_snapshot)

    def predict(
        self,
        page: RuntimeFlatMapPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult:
        raw, input_tokens, output_tokens = asyncio.run(
            self._call_provider(page, timeout_ms=timeout_ms)
        )
        payload = parse_payload(raw, response_type="object")
        validated, error = validate_task_payload(
            GENERALIZED_EXTRACTION_LLM_TASK,
            payload,
        )
        if error is not None or not isinstance(validated, dict):
            raise ValueError(error or "generalized extraction returned invalid JSON")
        predictions = tuple(
            ModelEvidenceCandidate.model_validate(
                {
                    **row,
                    "artifact_id": page.source.artifact_id,
                }
            )
            for row in validated.get("predictions", ())
            if isinstance(row, dict)
        )
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=predictions,
            latency_ms=0.0,
            memory_mb=0.0,
            cost_usd=float(
                estimate_cost_usd(
                    str(self._config.get("provider") or ""),
                    str(self._config.get("model") or ""),
                    input_tokens,
                    output_tokens,
                )
            ),
        )

    async def _call_provider(
        self,
        page: RuntimeFlatMapPage,
        *,
        timeout_ms: int,
    ) -> tuple[str, int, int]:
        provider = str(self._config.get("provider") or "")
        model = str(self._config.get("model") or "")
        task = GENERALIZED_EXTRACTION_PROMPT_REGISTRY[GENERALIZED_EXTRACTION_LLM_TASK]
        system_prompt = load_prompt_file(str(task["system_file"]))
        user_template = load_prompt_file(str(task["user_file"]))
        if not system_prompt.strip() or not user_template.strip():
            raise ValueError("generalized extraction prompt files missing")
        user_prompt = Template(user_template).safe_substitute(
            {
                "url": stringify_prompt_value(page.source.artifact_id),
                "surface": stringify_prompt_value(page.surface or "ecommerce_detail"),
                "field_senses": stringify_prompt_value(
                    _field_senses(page.surface)
                ),
                "page": stringify_prompt_value(_page_payload(page)),
            }
        )
        return await asyncio.wait_for(
            call_provider_with_retry(
                provider=provider,
                model=model,
                api_key=resolve_provider_api_key(
                    provider=provider,
                    encrypted_value=str(self._config.get("api_key_encrypted") or ""),
                ),
                system_prompt=system_prompt,
                user_prompt=enforce_token_limit(user_prompt),
                max_tokens=int(GENERALIZED_EXTRACTION_BUDGET["max_output_tokens"]),
            ),
            timeout=max(0.001, timeout_ms / 1_000),
        )


def _page_payload(page: RuntimeFlatMapPage) -> dict[str, Any]:
    return {
        "schema_version": page.schema_version,
        "token_count": page.token_count,
        "scope_path": page.scope_path,
        "fallback_reason": page.fallback_reason,
        "vision_recommended": page.vision_recommended,
        "path_to_text": {entry.path: entry.text for entry in page.entries},
    }


def _field_senses(surface: str) -> list[dict[str, str]]:
    schema = listing_schema(surface) if surface else None
    if schema is None:
        return list(GENERALIZED_EXTRACTION_FIELD_SENSES)
    return [
        {
            "field": fact_type.rsplit(".", 1)[-1],
            "fact_type": fact_type,
            "sense": f"visible record-local {fact_type}",
        }
        for fact_type in schema.bindable_facts
    ]


def hosted_generalized_adapter(
    *,
    config_snapshot: dict[str, Any],
) -> HostedGeneralizedExtractionAdapter | None:
    if not config_snapshot:
        return None
    return HostedGeneralizedExtractionAdapter(config_snapshot=config_snapshot)
