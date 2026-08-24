from __future__ import annotations

from urllib.parse import urlparse

from app.core.proxy_secrets import strip_url_userinfo

_SUPPORTED_BROWSER_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


def proxy_host_port(parsed) -> str:
    hostname = str(parsed.hostname or "").strip()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return hostname


def build_browser_proxy_config(proxy: str | None) -> dict[str, str] | None:
    raw_proxy = str(proxy or "").strip()
    if not raw_proxy:
        return None
    parsed = urlparse(raw_proxy)
    if not parsed.scheme:
        raise ValueError(
            "Browser proxy must include a scheme such as http:// or socks5://"
        )
    normalized_scheme = str(parsed.scheme or "").strip().lower()
    if normalized_scheme not in _SUPPORTED_BROWSER_PROXY_SCHEMES:
        raise ValueError(
            f"Unsupported browser proxy scheme: {normalized_scheme or parsed.scheme}"
        )
    if not parsed.hostname:
        raise ValueError("Browser proxy must include a hostname")
    server = f"{normalized_scheme}://{proxy_host_port(parsed)}"
    config = {"server": server}
    if parsed.username:
        config["username"] = parsed.username
    if parsed.username and parsed.password is not None:
        config["password"] = parsed.password
    return config


def normalized_proxy_value(proxy: str | None) -> str | None:
    value = str(proxy or "").strip()
    return value or None


def proxy_scheme(proxy: str | None) -> str | None:
    raw_proxy = normalized_proxy_value(proxy)
    if raw_proxy is None:
        return None
    parsed = urlparse(raw_proxy)
    return str(parsed.scheme or "").strip().lower() or None


def display_proxy(proxy: str | None) -> str:
    raw_proxy = str(proxy or "").strip()
    if not raw_proxy:
        return "direct"
    return strip_url_userinfo(raw_proxy, masked=True)


__all__ = [
    "build_browser_proxy_config",
    "display_proxy",
    "normalized_proxy_value",
    "proxy_scheme",
]
