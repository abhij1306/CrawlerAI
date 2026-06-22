from __future__ import annotations

from typing import Any

PoolKey = str | tuple[str, str]
EvictionCandidate = tuple[str, PoolKey, Any, float]


def evict_idle_browser_runtimes_locked(
    *,
    direct_pool: dict[str, Any],
    proxied_pool: dict[tuple[str, str], Any],
    idle_ttl_seconds: int,
    max_entries: int,
) -> list[Any]:
    pools = (("direct", direct_pool), ("proxied", proxied_pool))
    candidates = _ttl_candidates(pools, idle_ttl_seconds)
    while _pool_size(pools) - len(candidates) >= max_entries:
        remaining = _remaining_idle_candidates(pools, candidates)
        if not remaining:
            break
        candidates.append(_oldest_idle_candidate(remaining))

    runtimes_to_close: list[Any] = []
    for candidate in candidates:
        _pop_if_still_idle(candidate, direct_pool, proxied_pool, runtimes_to_close)

    while _pool_size(pools) > max_entries:
        remaining = _remaining_idle_candidates(pools, [])
        if not remaining:
            break
        _pop_if_still_idle(
            _oldest_idle_candidate(remaining),
            direct_pool,
            proxied_pool,
            runtimes_to_close,
        )
    return runtimes_to_close


def _pool_size(pools: tuple[tuple[str, dict[Any, Any]], ...]) -> int:
    return sum(len(pool) for _pool_name, pool in pools)


def _normalized_pool_key(pool_name: str, key: Any) -> PoolKey | None:
    if pool_name == "direct":
        return str(key)
    if isinstance(key, tuple) and len(key) == 2:
        return (str(key[0]), str(key[1]))
    return None


def _ttl_candidates(
    pools: tuple[tuple[str, dict[Any, Any]], ...],
    idle_ttl_seconds: int,
) -> list[EvictionCandidate]:
    if idle_ttl_seconds <= 0:
        return []
    rows: list[EvictionCandidate] = []
    for pool_name, pool in pools:
        for key, runtime in tuple(pool.items()):
            active_and_queued, last_used = runtime.eviction_key()
            normalized_key = _normalized_pool_key(pool_name, key)
            if (
                active_and_queued == 0
                and normalized_key is not None
                and runtime.idle_seconds() >= idle_ttl_seconds
            ):
                rows.append((pool_name, normalized_key, runtime, last_used))
    return rows


def _remaining_idle_candidates(
    pools: tuple[tuple[str, dict[Any, Any]], ...],
    excluded: list[EvictionCandidate],
) -> list[EvictionCandidate]:
    excluded_keys = {
        (pool_name, key) for pool_name, key, _runtime, _last_used in excluded
    }
    rows: list[EvictionCandidate] = []
    for pool_name, pool in pools:
        for key, runtime in tuple(pool.items()):
            active_and_queued, last_used = runtime.eviction_key()
            normalized_key = _normalized_pool_key(pool_name, key)
            if active_and_queued != 0 or normalized_key is None:
                continue
            if (pool_name, normalized_key) in excluded_keys:
                continue
            rows.append((pool_name, normalized_key, runtime, last_used))
    return rows


def _oldest_idle_candidate(candidates: list[EvictionCandidate]) -> EvictionCandidate:
    return min(candidates, key=lambda item: (item[2].eviction_key()[0], item[3]))


def _pop_if_still_idle(
    candidate: EvictionCandidate,
    direct_pool: dict[str, Any],
    proxied_pool: dict[tuple[str, str], Any],
    runtimes_to_close: list[Any],
) -> None:
    pool_name, key, runtime, candidate_last_used = candidate
    if pool_name == "direct":
        if not isinstance(key, str):
            return
        current = direct_pool.get(key)
        if current is None or current is not runtime:
            return
        active_and_queued, last_used = current.eviction_key()
        if active_and_queued != 0 or last_used != candidate_last_used:
            return
        direct_pool.pop(key, None)
        runtimes_to_close.append(runtime)
    elif isinstance(key, tuple):
        current = proxied_pool.get(key)
        if current is None or current is not runtime:
            return
        active_and_queued, last_used = current.eviction_key()
        if active_and_queued != 0 or last_used != candidate_last_used:
            return
        proxied_pool.pop(key, None)
        runtimes_to_close.append(runtime)
    else:
        return
