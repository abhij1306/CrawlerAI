from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

from app.core.shared.field_coerce import object_list


def http_cookie_pairs_for_url(
    url: str | None,
    storage_state: Mapping[str, object],
) -> list[tuple[str, str]]:
    scheme, host, path = _cookie_target(url)
    candidates: list[tuple[int, int, str, str]] = []
    for cookie in object_list(storage_state.get("cookies")):
        candidate = _http_cookie_candidate(
            cookie,
            scheme=scheme,
            host=host,
            path=path,
        )
        if candidate is not None:
            candidates.append(candidate)
    return _select_http_cookie_pairs(candidates)


def _http_cookie_candidate(
    cookie: object, *, scheme: str, host: str, path: str
) -> tuple[int, int, str, str] | None:
    if not isinstance(cookie, Mapping):
        return None
    name = str(cookie.get("name") or "").strip()
    value = str(cookie.get("value") or "").strip()
    if not name or value == "":
        return None
    if bool(cookie.get("secure")) and scheme != "https":
        return None
    domain = str(cookie.get("domain") or "").strip().lower()
    cookie_path = str(cookie.get("path") or "/").strip() or "/"
    if host and domain and not _cookie_domain_matches(host, domain):
        return None
    if path and not _cookie_path_matches(path, cookie_path):
        return None
    return len(domain.lstrip(".")), len(cookie_path), name, value


def _select_http_cookie_pairs(
    candidates: list[tuple[int, int, str, str]],
) -> list[tuple[str, str]]:
    selected: dict[str, tuple[int, int, str, str]] = {}
    for domain_score, path_score, name, value in candidates:
        key = name
        existing = selected.get(key)
        if existing is None or (domain_score, path_score) >= (
            existing[0],
            existing[1],
        ):
            selected[key] = (domain_score, path_score, name, value)
    return [
        (name, value)
        for _key, (_domain_score, _path_score, name, value) in selected.items()
    ]


def _cookie_target(url: str | None) -> tuple[str, str, str]:
    normalized = str(url or "").strip()
    if not normalized:
        return "", "", "/"
    parsed = urlparse(normalized if "://" in normalized else f"//{normalized}")
    return (
        str(parsed.scheme or "").strip().lower(),
        str(parsed.hostname or "").strip().lower(),
        str(parsed.path or "/").strip() or "/",
    )


def _cookie_domain_matches(host: str, domain: str) -> bool:
    normalized_domain = domain.lstrip(".")
    return host == normalized_domain or host.endswith(f".{normalized_domain}")


def _cookie_path_matches(request_path: str, cookie_path: str) -> bool:
    normalized_request_path = str(request_path or "/").strip() or "/"
    normalized_cookie_path = str(cookie_path or "/").strip() or "/"
    if normalized_request_path == normalized_cookie_path:
        return True
    if not normalized_request_path.startswith(normalized_cookie_path):
        return False
    suffix = normalized_request_path[
        len(normalized_cookie_path) : len(normalized_cookie_path) + 1
    ]
    return normalized_cookie_path.endswith("/") or suffix == "/"
