"""Initialize the rebuild database with the single baseline migration."""

import asyncio

from app.core.migrations import apply_pending_migrations_async


async def init_database():
    """Apply the canonical database schema."""
    await apply_pending_migrations_async()
    print("Database schema initialized successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
