import os

from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool

load_dotenv()

database_url = os.environ.get("HIVE_DB_URL")
if not database_url:
    raise RuntimeError("HIVE_DB_URL not set")

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    global _pool

    if _pool is None:
        _pool = AsyncConnectionPool(conninfo=database_url, open=False)
        await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None
