# Async database engine and session factory.
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.core.config import settings
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import CreateColumn

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_database_url = make_url(settings.database_url)
_engine_kwargs: dict[str, object] = {
    "future": True,
    "echo": False,
}
if not _database_url.drivername.startswith("sqlite"):
    _engine_kwargs["pool_size"] = settings.db_pool_size
    _engine_kwargs["max_overflow"] = settings.db_max_overflow
    _engine_kwargs["pool_pre_ping"] = settings.db_pool_pre_ping
    _engine_kwargs["pool_recycle"] = settings.db_pool_recycle_seconds
    _engine_kwargs["pool_timeout"] = settings.db_pool_timeout_seconds

engine = create_async_engine(settings.database_url, **_engine_kwargs)
SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
    autoflush=False,
)


async def ensure_database_schema() -> None:
    """Create ORM-owned tables for rebuild deployments without Alembic files."""
    import app.models  # noqa: F401  # register model metadata

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_create_missing_columns)


def _create_missing_columns(connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    preparer = connection.dialect.identifier_preparer
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        existing_columns = {
            row["name"]
            for row in inspector.get_columns(table.name, schema=table.schema)
        }
        for column in table.columns:
            if column.name in existing_columns:
                continue
            column_sql = str(CreateColumn(column).compile(dialect=connection.dialect))
            table_sql = preparer.format_table(table)
            logger.warning(
                "Adding missing database column %s.%s", table.name, column.name
            )
            connection.execute(text(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql}"))


async def dispose_engine() -> None:
    """Dispose the connection pool. Call during application shutdown."""
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            try:
                await session.rollback()
            except Exception:
                logger.debug("Session rollback failed during teardown", exc_info=True)
            raise
