import importlib
import os
import sys

import dotenv
import psycopg
import pytest


async def test_pool_connects(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute("SELECT 1")
        assert await cursor.fetchone() == (1,)


async def test_migrations_create_schema(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'hive' AND table_name = 'sections'
            )
            """
        )
        assert await cursor.fetchone() == (True,)


async def test_migrations_idempotent(db_pool):
    from coordinator.db.migrate import run_migrations

    await run_migrations(db_pool)
    await run_migrations(db_pool)


async def test_insert_section(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.sections (name, description, priority, status)
            VALUES (%s, %s, %s, %s)
            RETURNING name, description, priority, status
            """,
            ("Planning", "Initial planning", 3, "active"),
        )
        assert await cursor.fetchone() == (
            "Planning",
            "Initial planning",
            3,
            "active",
        )


async def test_insert_task(db_pool):
    async with db_pool.connection() as conn:
        section_cursor = await conn.execute(
            """
            INSERT INTO hive.sections (name, description, priority, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            ("Build", "Build tasks", 5, "active"),
        )
        section_id = (await section_cursor.fetchone())[0]

        task_cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (
                section_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING
                section_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs
            """,
            (
                section_id,
                "Implement connection pool",
                "Create psycopg pool",
                "open",
                1,
                "codex",
                42,
                ["docs/design/COORDINATOR.md"],
            ),
        )
        assert await task_cursor.fetchone() == (
            section_id,
            "Implement connection pool",
            "Create psycopg pool",
            "open",
            1,
            "codex",
            42,
            ["docs/design/COORDINATOR.md"],
        )


async def test_insert_task_no_section(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING section_id, title, status, sequence_order, relevant_docs
            """,
            (None, "Unassigned task", "open", 0, []),
        )
        assert await cursor.fetchone() == (
            None,
            "Unassigned task",
            "open",
            0,
            [],
        )


async def test_insert_clarification(db_pool):
    async with db_pool.connection() as conn:
        task_cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (None, "Blocked task", "open", 2, []),
        )
        task_id = (await task_cursor.fetchone())[0]

        clarification_cursor = await conn.execute(
            """
            INSERT INTO hive.clarifications (task_id, asked_by, question, answer, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING task_id, asked_by, question, answer, status
            """,
            (task_id, "codex", "Need more detail?", None, "pending"),
        )
        assert await clarification_cursor.fetchone() == (
            task_id,
            "codex",
            "Need more detail?",
            None,
            "pending",
        )


async def test_insert_task_note(db_pool):
    async with db_pool.connection() as conn:
        task_cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (title, status, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            ("Task with note", "open", 0, []),
        )
        task_id = (await task_cursor.fetchone())[0]

        note_cursor = await conn.execute(
            """
            INSERT INTO hive.task_notes (task_id, author, content)
            VALUES (%s, %s, %s)
            RETURNING task_id, author, content
            """,
            (task_id, "codex", "Started implementation"),
        )
        assert await note_cursor.fetchone() == (
            task_id,
            "codex",
            "Started implementation",
        )


async def test_task_note_fk_constraint(db_pool):
    async with db_pool.connection() as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await conn.execute(
                """
                INSERT INTO hive.task_notes (task_id, author, content)
                VALUES (%s, %s, %s)
                """,
                (9999, "codex", "Missing task"),
            )


async def test_task_status_constraint(db_pool):
    async with db_pool.connection() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            await conn.execute(
                """
                INSERT INTO hive.tasks (section_id, title, status, sequence_order, relevant_docs)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (None, "Bad status", "invalid", 0, []),
            )


async def test_relevant_docs_array(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING relevant_docs
            """,
            (None, "Docs task", "open", 3, ["url1", "url2"]),
        )
        assert await cursor.fetchone() == (["url1", "url2"],)


async def test_clean_db_fixture(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM hive.sections")
        assert await cursor.fetchone() == (0,)


async def test_clean_db_clears_task_notes(db_pool):
    async with db_pool.connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM hive.task_notes")
        assert await cursor.fetchone() == (0,)


def test_missing_hive_db_url_raises(monkeypatch):
    monkeypatch.delenv("HIVE_DB_URL", raising=False)
    monkeypatch.delenv("HIVE_TEST_DB_URL", raising=False)
    monkeypatch.delenv("HIVE_TESTING", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    sys.modules.pop("coordinator.db.connection", None)

    with pytest.raises(RuntimeError, match="HIVE_DB_URL not set"):
        importlib.import_module("coordinator.db.connection")
