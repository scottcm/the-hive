import pytest

from coordinator.mcp.tools import tasks


async def insert_section(
    db_pool,
    *,
    name: str,
    description: str | None = None,
    priority: int = 0,
    status: str = "active",
    assigned_to: str | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.sections (name, description, priority, status, assigned_to)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (name, description, priority, status, assigned_to),
        )
        return (await cursor.fetchone())[0]


async def insert_task(
    db_pool,
    *,
    title: str,
    section_id: int | None = None,
    description: str | None = None,
    status: str = "open",
    priority: int = 0,
    sequence_order: int = 0,
    assigned_to: str | None = None,
    github_issue: int | None = None,
    relevant_docs: list[str] | None = None,
    notes: str | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (
                section_id,
                title,
                description,
                status,
                priority,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                section_id,
                title,
                description,
                status,
                priority,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs or [],
                notes,
            ),
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


async def fetch_task_row(db_pool, task_id: int) -> tuple:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT
                section_id,
                title,
                description,
                status,
                priority,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs,
                notes,
                updated_at
            FROM hive.tasks
            WHERE id = %s
            """,
            (task_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row


async def test_get_current_task_in_progress(db_pool):
    section_id = await insert_section(db_pool, name="Core", priority=5)
    open_task_id = await insert_task(
        db_pool,
        title="Open task",
        section_id=section_id,
        status="open",
        assigned_to="codex",
        sequence_order=1,
    )
    in_progress_task_id = await insert_task(
        db_pool,
        title="Current task",
        section_id=section_id,
        status="in_progress",
        assigned_to="codex",
        sequence_order=2,
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["id"] == in_progress_task_id
    assert task["status"] == "in_progress"
    assert task["title"] == "Current task"
    assert task["id"] != open_task_id


async def test_get_current_task_falls_back_to_open(db_pool):
    section_id = await insert_section(db_pool, name="Core")
    task_id = await insert_task(
        db_pool,
        title="Assigned open task",
        section_id=section_id,
        status="open",
        assigned_to="codex",
        sequence_order=3,
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["id"] == task_id
    assert task["status"] == "open"


async def test_get_current_task_none(db_pool):
    section_id = await insert_section(db_pool, name="Core")
    await insert_task(
        db_pool,
        title="Other agent task",
        section_id=section_id,
        status="open",
        assigned_to="claude",
    )

    assert await tasks.get_current_task("codex") is None


async def test_get_current_task_includes_section_name(db_pool):
    section_id = await insert_section(db_pool, name="Planner")
    await insert_task(
        db_pool,
        title="Named section task",
        section_id=section_id,
        status="in_progress",
        assigned_to="codex",
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["section_name"] == "Planner"


async def test_get_current_task_includes_pending_clarifications(db_pool):
    section_id = await insert_section(db_pool, name="Core")
    task_id = await insert_task(
        db_pool,
        title="Blocked task",
        section_id=section_id,
        status="in_progress",
        assigned_to="codex",
    )
    pending_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Need detail?",
    )
    await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Already resolved?",
        answer="Yes",
        status="answered",
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["pending_clarifications"] == [
        {"id": pending_id, "question": "Need detail?", "status": "pending"}
    ]


async def test_get_next_task_prefers_assigned(db_pool):
    high_priority_section = await insert_section(db_pool, name="Urgent", priority=10)
    lower_priority_section = await insert_section(db_pool, name="Assigned", priority=1)
    await insert_task(
        db_pool,
        title="Unassigned urgent",
        section_id=high_priority_section,
        status="open",
        assigned_to=None,
        sequence_order=1,
    )
    assigned_task_id = await insert_task(
        db_pool,
        title="Assigned open",
        section_id=lower_priority_section,
        status="open",
        assigned_to="codex",
        sequence_order=5,
    )

    task = await tasks.get_next_task("codex")

    assert task is not None
    assert task["id"] == assigned_task_id
    assert task["assigned_to"] == "codex"


async def test_get_next_task_falls_back_unassigned(db_pool):
    section_id = await insert_section(db_pool, name="Shared", priority=7)
    task_id = await insert_task(
        db_pool,
        title="Shared task",
        section_id=section_id,
        status="open",
        assigned_to=None,
    )

    task = await tasks.get_next_task("codex")

    assert task is not None
    assert task["id"] == task_id
    assert task["assigned_to"] is None


async def test_get_next_task_none(db_pool):
    await insert_task(db_pool, title="Done task", status="done", assigned_to="codex")

    assert await tasks.get_next_task("codex") is None


async def test_list_tasks_no_filter(db_pool):
    lower_section_id = await insert_section(db_pool, name="Lower", priority=1)
    higher_section_id = await insert_section(db_pool, name="Higher", priority=9)
    first_id = await insert_task(
        db_pool,
        title="Higher first",
        section_id=higher_section_id,
        sequence_order=1,
    )
    second_id = await insert_task(
        db_pool,
        title="Higher second",
        section_id=higher_section_id,
        sequence_order=2,
    )
    third_id = await insert_task(
        db_pool,
        title="Lower only",
        section_id=lower_section_id,
        sequence_order=1,
    )

    result = await tasks.list_tasks()

    assert [task["id"] for task in result] == [first_id, second_id, third_id]
    assert result[0]["section_name"] == "Higher"
    assert result[2]["section_name"] == "Lower"


async def test_list_tasks_by_status(db_pool):
    await insert_task(db_pool, title="Open task", status="open")
    done_id = await insert_task(db_pool, title="Done task", status="done")

    result = await tasks.list_tasks(status="done")

    assert [task["id"] for task in result] == [done_id]
    assert result[0]["status"] == "done"


async def test_list_tasks_by_assigned_to(db_pool):
    codex_id = await insert_task(db_pool, title="Codex task", assigned_to="codex")
    await insert_task(db_pool, title="Claude task", assigned_to="claude")

    result = await tasks.list_tasks(assigned_to="codex")

    assert [task["id"] for task in result] == [codex_id]
    assert result[0]["assigned_to"] == "codex"


async def test_update_task_status(db_pool):
    task_id = await insert_task(db_pool, title="Status task", status="open")
    before_row = await fetch_task_row(db_pool, task_id)

    async with db_pool.connection() as conn:
        await conn.execute("SELECT pg_sleep(0.01)")

    task = await tasks.update_task(task_id, status="in_progress")
    after_row = await fetch_task_row(db_pool, task_id)

    assert task["id"] == task_id
    assert task["status"] == "in_progress"
    assert before_row[-1] < after_row[-1]


async def test_update_task_notes(db_pool):
    task_id = await insert_task(db_pool, title="Notes task", notes=None)

    task = await tasks.update_task(task_id, notes="Investigating edge cases")
    row = await fetch_task_row(db_pool, task_id)

    assert task["notes"] == "Investigating edge cases"
    assert row[9] == "Investigating edge cases"


async def test_update_task_not_found():
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.update_task(9999, status="done")


async def test_update_task_invalid_status(db_pool):
    task_id = await insert_task(db_pool, title="Bad status task")

    with pytest.raises(ValueError, match="Invalid status"):
        await tasks.update_task(task_id, status="invalid")


async def test_create_task_minimal(db_pool):
    task = await tasks.create_task("Minimal task")
    row = await fetch_task_row(db_pool, task["id"])

    assert task["title"] == "Minimal task"
    assert task["description"] is None
    assert task["status"] == "open"
    assert task["assigned_to"] is None
    assert task["section_id"] is None
    assert task["section_name"] is None
    assert task["github_issue"] is None
    assert task["relevant_docs"] == []
    assert task["notes"] is None
    assert task["sequence_order"] == 0
    assert row[:10] == (None, "Minimal task", None, "open", 0, 0, None, None, [], None)


async def test_create_task_full(db_pool):
    section_id = await insert_section(db_pool, name="Delivery", priority=4)

    task = await tasks.create_task(
        "Full task",
        description="Implement everything",
        section_id=section_id,
        assigned_to="codex",
        priority=8,
        sequence_order=3,
        github_issue=17,
        relevant_docs=["doc://one", "doc://two"],
    )
    row = await fetch_task_row(db_pool, task["id"])

    assert task == {
        "id": task["id"],
        "title": "Full task",
        "description": "Implement everything",
        "status": "open",
        "assigned_to": "codex",
        "section_id": section_id,
        "section_name": "Delivery",
        "github_issue": 17,
        "relevant_docs": ["doc://one", "doc://two"],
        "notes": None,
        "sequence_order": 3,
    }
    assert row[:10] == (
        section_id,
        "Full task",
        "Implement everything",
        "open",
        8,
        3,
        "codex",
        17,
        ["doc://one", "doc://two"],
        None,
    )


async def test_create_task_relevant_docs(db_pool):
    task = await tasks.create_task(
        "Docs task",
        relevant_docs=["https://example.com/a", "https://example.com/b"],
    )
    row = await fetch_task_row(db_pool, task["id"])

    assert task["relevant_docs"] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert row[8] == ["https://example.com/a", "https://example.com/b"]
