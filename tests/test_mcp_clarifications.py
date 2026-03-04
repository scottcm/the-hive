import pytest

from coordinator.mcp.tools import clarifications


async def insert_task(
    db_pool,
    *,
    title: str,
    status: str = "open",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, priority, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (None, title, status, 0, 0, []),
        )
        return (await cursor.fetchone())[0]


async def insert_clarification(
    db_pool,
    *,
    task_id: int,
    asked_by: str,
    question: str,
    answer: str | None = None,
    status: str = "pending",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.clarifications (task_id, asked_by, question, answer, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (task_id, asked_by, question, answer, status),
        )
        return (await cursor.fetchone())[0]


async def fetch_task_status(db_pool, task_id: int) -> str:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT status FROM hive.tasks WHERE id = %s",
            (task_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row[0]


async def fetch_clarification_row(db_pool, clarification_id: int) -> tuple:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT task_id, asked_by, question, answer, status, answered_at
            FROM hive.clarifications
            WHERE id = %s
            """,
            (clarification_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row


async def test_create_clarification(db_pool):
    task_id = await insert_task(db_pool, title="Blocked soon")

    clarification = await clarifications.create_clarification(
        task_id=task_id,
        asked_by="codex",
        question="What should happen here?",
    )

    assert clarification == {
        "id": clarification["id"],
        "task_id": task_id,
        "asked_by": "codex",
        "question": "What should happen here?",
        "status": "pending",
    }
    assert await fetch_task_status(db_pool, task_id) == "blocked"


async def test_create_clarification_task_not_found():
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await clarifications.create_clarification(
            task_id=9999,
            asked_by="codex",
            question="Missing task?",
        )


async def test_answer_clarification(db_pool):
    task_id = await insert_task(db_pool, title="Blocked task", status="blocked")
    clarification_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Need detail?",
    )

    clarification = await clarifications.answer_clarification(
        clarification_id=clarification_id,
        answer="Use the default path.",
    )
    row = await fetch_clarification_row(db_pool, clarification_id)

    assert clarification["id"] == clarification_id
    assert clarification["task_id"] == task_id
    assert clarification["asked_by"] == "codex"
    assert clarification["question"] == "Need detail?"
    assert clarification["answer"] == "Use the default path."
    assert clarification["status"] == "answered"
    assert row[5] is not None


async def test_answer_clarification_does_not_unblock_task(db_pool):
    task_id = await insert_task(db_pool, title="Still blocked", status="blocked")
    clarification_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Need approval?",
    )

    await clarifications.answer_clarification(
        clarification_id=clarification_id,
        answer="Approved.",
    )

    assert await fetch_task_status(db_pool, task_id) == "blocked"


async def test_answer_clarification_not_found():
    with pytest.raises(ValueError, match="Clarification 9999 not found"):
        await clarifications.answer_clarification(clarification_id=9999, answer="Nope")
