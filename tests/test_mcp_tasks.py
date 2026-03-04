import pytest

from coordinator.mcp.tools import tasks


async def insert_section(
    db_pool,
    *,
    name: str,
    description: str | None = None,
    priority: int = 0,
    status: str = "active",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.sections (name, description, priority, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (name, description, priority, status),
        )
        return (await cursor.fetchone())[0]


async def insert_task(
    db_pool,
    *,
    title: str,
    section_id: int | None = None,
    description: str | None = None,
    status: str = "open",
    sequence_order: int = 0,
    assigned_to: str | None = None,
    github_issue: int | None = None,
    relevant_docs: list[str] | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
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
            RETURNING id
            """,
            (
                section_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs or [],
            ),
        )
        return (await cursor.fetchone())[0]


async def insert_note(
    db_pool,
    *,
    task_id: int,
    author: str,
    content: str,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.task_notes (task_id, author, content)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (task_id, author, content),
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
                sequence_order,
                assigned_to,
                github_issue,
                relevant_docs,
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
    await insert_task(
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


async def test_get_current_task_falls_back_to_open(db_pool):
    section_id = await insert_section(db_pool, name="Core")
    task_id = await insert_task(
        db_pool,
        title="Assigned open task",
        section_id=section_id,
        status="open",
        assigned_to="codex",
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


async def test_get_current_task_includes_section_info(db_pool):
    section_id = await insert_section(
        db_pool,
        name="Planner",
        description="Planning work",
    )
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
    assert task["section_description"] == "Planning work"


async def test_get_current_task_includes_notes(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Task with notes",
        status="in_progress",
        assigned_to="codex",
    )
    note_id = await insert_note(
        db_pool,
        task_id=task_id,
        author="scott",
        content="Use the provider abstraction.",
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["notes"] == [
        {
            "id": note_id,
            "author": "scott",
            "content": "Use the provider abstraction.",
            "created_at": task["notes"][0]["created_at"],
        }
    ]


async def test_get_current_task_includes_pending_clarifications(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Blocked task",
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


async def test_claim_task_success(db_pool):
    section_id = await insert_section(
        db_pool,
        name="Build",
        description="Build tasks",
        priority=5,
    )
    task_id = await insert_task(
        db_pool,
        title="Claim me",
        section_id=section_id,
        status="open",
    )
    note_id = await insert_note(
        db_pool,
        task_id=task_id,
        author="scott",
        content="Ready for pickup.",
    )
    clarification_id = await insert_clarification(
        db_pool,
        task_id=task_id,
        asked_by="codex",
        question="Should not appear because answered.",
        answer="Resolved",
        status="answered",
    )

    task = await tasks.claim_task(task_id, "codex")
    row = await fetch_task_row(db_pool, task_id)

    assert task["id"] == task_id
    assert task["status"] == "in_progress"
    assert task["assigned_to"] == "codex"
    assert task["section_name"] == "Build"
    assert task["section_description"] == "Build tasks"
    assert task["notes"] == [
        {
            "id": note_id,
            "author": "scott",
            "content": "Ready for pickup.",
            "created_at": task["notes"][0]["created_at"],
        }
    ]
    assert task["pending_clarifications"] == []
    assert clarification_id is not None
    assert row[:8] == (section_id, "Claim me", None, "in_progress", 0, "codex", None, [])


async def test_claim_task_already_claimed(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Claimed",
        status="in_progress",
        assigned_to="claude",
    )

    with pytest.raises(ValueError, match=f"Task {task_id} is not open"):
        await tasks.claim_task(task_id, "codex")


async def test_claim_task_blocked(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Blocked",
        status="blocked",
    )

    with pytest.raises(ValueError, match=f"Task {task_id} is not open"):
        await tasks.claim_task(task_id, "codex")


async def test_release_task(db_pool):
    task_id = await insert_task(
        db_pool,
        title="Release me",
        status="in_progress",
        assigned_to="codex",
    )

    task = await tasks.release_task(task_id)
    row = await fetch_task_row(db_pool, task_id)

    assert task["id"] == task_id
    assert task["status"] == "open"
    assert task["assigned_to"] is None
    assert task["notes"] == []
    assert task["pending_clarifications"] == []
    assert row[:8] == (None, "Release me", None, "open", 0, None, None, [])


async def test_list_tasks_no_filter(db_pool):
    lower_section_id = await insert_section(
        db_pool,
        name="Lower",
        description="Lower priority",
        priority=1,
    )
    higher_section_id = await insert_section(
        db_pool,
        name="Higher",
        description="Higher priority",
        priority=9,
    )
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
    assert result[0]["section_description"] == "Higher priority"
    assert "notes" not in result[0]
    assert "pending_clarifications" not in result[0]


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


async def test_update_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.update_task(9999, status="done")


async def test_update_task_invalid_status(db_pool):
    task_id = await insert_task(db_pool, title="Bad status task")

    with pytest.raises(ValueError, match="Invalid status"):
        await tasks.update_task(task_id, status="invalid")


async def test_create_task_minimal(db_pool):
    task = await tasks.create_task("Minimal task")
    row = await fetch_task_row(db_pool, task["id"])

    assert task == {
        "id": task["id"],
        "title": "Minimal task",
        "description": None,
        "status": "open",
        "assigned_to": None,
        "section_id": None,
        "section_name": None,
        "section_description": None,
        "github_issue": None,
        "relevant_docs": [],
        "sequence_order": 0,
    }
    assert row[:8] == (None, "Minimal task", None, "open", 0, None, None, [])
