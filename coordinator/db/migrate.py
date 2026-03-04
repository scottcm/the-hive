from pathlib import Path

from psycopg_pool import AsyncConnectionPool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def run_migrations(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS hive")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hive.migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cursor = await conn.execute("SELECT filename FROM hive.migrations")
        applied = {row[0] for row in await cursor.fetchall()}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue

            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO hive.migrations (filename) VALUES (%s)",
                    (path.name,),
                )
            applied.add(path.name)
