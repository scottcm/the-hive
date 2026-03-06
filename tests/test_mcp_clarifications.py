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
            INSERT INTO hive.tasks (milestone_id, title, status, sequence_order, relevant_docs, tags, github_issues)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (None, title, status, 0, [], [], []),
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


async def test_create_clarification_task_not_found(db_pool):
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


async def test_answer_auto_unblocks_when_all_answered(db_pool):
    task_id = await insert_task(db_pool, title="Auto unblock", status="blocked")
    clarification_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Last question?",
    )

    await clarifications.answer_clarification(
        clarification_id=clarification_id,
        answer="Yes.",
    )

    assert await fetch_task_status(db_pool, task_id) == "open"


async def test_answer_does_not_unblock_with_pending(db_pool):
    task_id = await insert_task(db_pool, title="Still blocked", status="blocked")
    first_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="First?",
    )
    await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Second?",
    )

    await clarifications.answer_clarification(
        clarification_id=first_id,
        answer="Only one answered.",
    )

    assert await fetch_task_status(db_pool, task_id) == "blocked"


async def test_answer_clarification_not_found(db_pool):
    with pytest.raises(ValueError, match="Clarification 9999 not found"):
        await clarifications.answer_clarification(clarification_id=9999, answer="Nope")


async def test_list_clarifications_all(db_pool):
    first_task_id = await insert_task(db_pool, title="First task")
    second_task_id = await insert_task(db_pool, title="Second task")
    answered_id = await insert_clarification(
        db_pool,
        task_id=first_task_id,
        asked_by="codex",
        question="Answered question?",
        answer="Done",
        status="answered",
    )
    pending_id = await insert_clarification(
        db_pool,
        task_id=second_task_id,
        asked_by="claude",
        question="Pending question?",
    )

    result = await clarifications.list_clarifications()

    assert [item["id"] for item in result] == [pending_id, answered_id]
    assert result[0]["task_title"] == "Second task"
    assert result[1]["task_title"] == "First task"


async def test_list_clarifications_filter_by_status(db_pool):
    task_id = await insert_task(db_pool, title="Task")
    await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Answered question?",
        answer="Done",
        status="answered",
    )
    pending_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Pending question?",
    )

    result = await clarifications.list_clarifications(status="pending")

    assert [item["id"] for item in result] == [pending_id]
    assert result[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# get_clarification
# ---------------------------------------------------------------------------


async def test_get_clarification_returns_full_record(db_pool):
    task_id = await insert_task(db_pool, title="Get clarification task")
    clar_id = await insert_clarification(
        db_pool, task_id=task_id, asked_by="codex", question="What should I do?"
    )

    clar = await clarifications.get_clarification(clar_id)

    assert clar["id"] == clar_id
    assert clar["task_id"] == task_id
    assert clar["asked_by"] == "codex"
    assert clar["question"] == "What should I do?"
    assert clar["status"] == "pending"
    assert clar["answer"] is None
    assert "created_at" in clar
    assert "answered_at" in clar


async def test_get_clarification_answered(db_pool):
    task_id = await insert_task(db_pool, title="Answered task", status="blocked")
    clar_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Need detail?",
        answer="Yes, use the default.",
        status="answered",
    )

    clar = await clarifications.get_clarification(clar_id)

    assert clar["id"] == clar_id
    assert clar["status"] == "answered"
    assert clar["answer"] == "Yes, use the default."


async def test_get_clarification_not_found(db_pool):
    with pytest.raises(ValueError, match="Clarification 9999 not found"):
        await clarifications.get_clarification(9999)
