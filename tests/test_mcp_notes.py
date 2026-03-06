import pytest

from coordinator.mcp.tools import notes, tasks


async def insert_task(
    db_pool,
    *,
    title: str,
    status: str = "open",
    assigned_to: str | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (title, status, sequence_order, assigned_to, relevant_docs)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (title, status, 0, assigned_to, []),
        )
        return (await cursor.fetchone())[0]


async def test_add_note(db_pool):
    task_id = await insert_task(db_pool, title="Task with note")

    note = await notes.add_note(task_id=task_id, author="codex", content="Started work")

    assert note["id"] > 0
    assert note["task_id"] == task_id
    assert note["author"] == "codex"
    assert note["content"] == "Started work"
    assert isinstance(note["created_at"], str)


async def test_add_note_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await notes.add_note(task_id=9999, author="codex", content="Missing task")


async def test_add_note_appears_in_get_current_task(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Current task",
        status="in_progress",
        assigned_to="codex",
    )

    note = await notes.add_note(task_id=task_id, author="codex", content="Investigating")
    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["notes"] == [
        {
            "id": note["id"],
            "author": "codex",
            "content": "Investigating",
            "created_at": note["created_at"],
        }
    ]


# ---------------------------------------------------------------------------
# list_notes
# ---------------------------------------------------------------------------


async def test_list_notes_returns_notes_for_task(db_pool):
    task_id = await insert_task(db_pool, title="Notes task")
    await notes.add_note(task_id=task_id, author="codex", content="First note")
    await notes.add_note(task_id=task_id, author="claude-scott", content="Second note")

    result = await notes.list_notes(task_id)

    assert len(result) == 2
    note = result[0]
    assert "id" in note
    assert "task_id" in note
    assert "author" in note
    assert "content" in note
    assert "created_at" in note


async def test_list_notes_returns_empty_for_task_with_no_notes(db_pool):
    task_id = await insert_task(db_pool, title="Empty notes task")
    result = await notes.list_notes(task_id)
    assert result == []


async def test_list_notes_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await notes.list_notes(9999)


async def test_list_notes_ordered_newest_first(db_pool):
    task_id = await insert_task(db_pool, title="Ordered notes task")
    note_a = await notes.add_note(task_id=task_id, author="codex", content="Alpha")
    note_b = await notes.add_note(task_id=task_id, author="codex", content="Beta")

    result = await notes.list_notes(task_id)

    assert result[0]["id"] == note_b["id"]
    assert result[1]["id"] == note_a["id"]


async def test_list_notes_limit(db_pool):
    task_id = await insert_task(db_pool, title="Limit notes task")
    for i in range(5):
        await notes.add_note(task_id=task_id, author="codex", content=f"Note {i}")

    result = await notes.list_notes(task_id, limit=3)
    assert len(result) == 3
