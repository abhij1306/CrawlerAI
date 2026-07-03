from app.core.config import extraction_memory as cfg
from app.core.extraction_memory.templates import normalize_source_pattern


def merge_observed_sources(contract: dict, sources: list[str]) -> None:
    canonical_sources = [
        source for row in sources if (source := _normalized_source(row))
    ]
    candidates = _candidates_by_source(contract)
    for source in canonical_sources:
        candidate = candidates.setdefault(
            source, {"source": source, "success_count": 0}
        )
        candidate["success_count"] = _success_count(candidate) + 1
    current_source = _normalized_source(contract.get("selected_source"))
    if current_source:
        contract["selected_source"] = current_source
    if current_source and current_source not in canonical_sources:
        contract["rejection_count"] = int(contract.get("rejection_count") or 0) + 1
    contract["success_count"] = int(contract.get("success_count") or 0) + 1
    ordered = sorted(
        candidates.values(),
        key=lambda row: (-_success_count(row), str(row.get("source"))),
    )
    contract["candidates"] = _limited(ordered, candidates.get(current_source))
    _promote_observed_source(contract, candidates, ordered, current_source)


def _candidates_by_source(contract: dict) -> dict[str, dict]:
    candidates: dict[str, dict] = {}
    for row in contract.get("candidates", []):
        if not isinstance(row, dict):
            continue
        source = _normalized_source(row.get("source"))
        if source:
            candidates[source] = dict(row, source=source)
    return candidates


def _limited(ordered: list[dict], selected: dict | None) -> list[dict]:
    limited = ordered[: cfg.EXTRACTION_CONTRACT_CANDIDATE_LIMIT]
    if selected is not None and selected not in limited:
        limited[-1:] = [selected]
    return limited


def _promote_observed_source(
    contract: dict,
    candidates: dict[str, dict],
    ordered: list[dict],
    current_source: str,
) -> None:
    if not ordered or str(contract.get("selection_origin") or "") != (
        cfg.EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC
    ):
        return
    best_source = str(ordered[0].get("source") or "")
    current_count = _success_count(candidates.get(current_source) or {})
    selected_source = (
        current_source if current_count == _success_count(ordered[0]) else best_source
    )
    if selected_source == current_source:
        return
    contract["selected_source"] = selected_source
    history = list(contract.get("selection_history") or [])
    entry = {
        "selected_source": selected_source,
        "source": cfg.EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
    }
    history.append(entry)
    contract["selection_history"] = history[-cfg.EXTRACTION_CONTRACT_HISTORY_LIMIT :]


def _success_count(candidate: dict) -> int:
    return int(candidate.get("success_count") or 0)


def _normalized_source(value: object) -> str:
    return normalize_source_pattern(str(value or ""))
