"""Initialize the rebuild database with the single baseline migration."""
import asyncio

from app.core.database import ensure_database_schema
from app.core.migrations import apply_pending_migrations_async


async def init_database():
    """Apply the baseline revision and reconcile ORM-owned columns."""
    await apply_pending_migrations_async()
    await ensure_database_schema()
    print("Database schema initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
