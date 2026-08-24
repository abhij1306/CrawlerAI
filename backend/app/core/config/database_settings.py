"""Database deployment-component composition and production validation."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlsplit


def build_database_url(
    *,
    complete_url: str,
    host: str,
    port: int,
    name: str,
    user: str,
    password: str,
) -> str:
    supplied = str(complete_url or "").strip()
    if supplied:
        return supplied
    required = {
        "host": str(host or "").strip(),
        "name": str(name or "").strip(),
        "user": str(user or "").strip(),
        "password": str(password or ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError(
            "DATABASE_URL or complete database components are required; missing: "
            + ", ".join(missing)
        )
    normalized_host = required["host"]
    if ":" in normalized_host and not normalized_host.startswith("["):
        normalized_host = f"[{normalized_host}]"
    encoded_user = quote(required["user"], safe="")
    encoded_password = quote(required["password"], safe="")
    encoded_name = quote(required["name"], safe="")
    return (
        f"postgresql+asyncpg://{encoded_user}:{encoded_password}"
        f"@{normalized_host}:{int(port)}/{encoded_name}"
    )


def production_database_issues(database_url: str) -> list[str]:
    raw = str(database_url or "").strip()
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError:
        return ["database_url is invalid"]
    issues: list[str] = []
    if not parsed.scheme.startswith("postgresql"):
        issues.append("database_url must use PostgreSQL outside dev/test")
    if str(parsed.hostname or "").lower() in {"", "localhost", "127.0.0.1", "::1"}:
        issues.append("database_url must not target localhost outside dev/test")
    password = unquote(str(parsed.password or ""))
    if not password or password.lower() in {
        "postgres",
        "password",
        "change-me",
        "replace-with-local-postgres-password",
    }:
        issues.append("database_url must contain a non-placeholder password")
    return issues
