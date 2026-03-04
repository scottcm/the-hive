import asyncio
import os

import pytest
from dotenv import load_dotenv

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()

test_db_url = os.environ.get("HIVE_TEST_DB_URL")
if test_db_url:
    os.environ["HIVE_DB_URL"] = test_db_url
os.environ["HIVE_TESTING"] = "1"

from coordinator.db.connection import close_pool, get_pool
from coordinator.db.migrate import run_migrations


@pytest.fixture(scope="session")
async def db_pool():
    pool = await get_pool()
    await run_migrations(pool)
    yield pool
    await close_pool()


async def _reset_db(db_pool) -> None:
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            TRUNCATE hive.clarifications, hive.task_notes, hive.tasks, hive.milestones, hive.projects
            RESTART IDENTITY CASCADE
            """
        )


@pytest.fixture(autouse=True)
async def clean_db(request):
    if request.node.name == "test_missing_hive_db_url_raises":
        yield
        return

    db_pool = request.getfixturevalue("db_pool")
    await _reset_db(db_pool)
    yield
    await _reset_db(db_pool)
