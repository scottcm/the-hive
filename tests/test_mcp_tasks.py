import pytest

from coordinator.mcp.tools import tasks


async def insert_milestone(
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
            INSERT INTO hive.milestones (name, description, priority, status)
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
    milestone_id: int | None = None,
    description: str | None = None,
    status: str = "open",
    sequence_order: int = 0,
    assigned_to: str | None = None,
    github_issues: list[int] | None = None,
    tags: list[str] | None = None,
    relevant_docs: list[str] | None = None,
    depends_on: list[int] | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (
                milestone_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issues,
                tags,
                relevant_docs,
                depends_on
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                milestone_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issues or [],
                tags or [],
                relevant_docs or [],
                depends_on or [],
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
                milestone_id,
                title,
                description,
                status,
                sequence_order,
                assigned_to,
                github_issues,
                tags,
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
    milestone_id = await insert_milestone(db_pool, name="Core", priority=5)
    await insert_task(
        db_pool,
        title="Open task",
        milestone_id=milestone_id,
        status="open",
        assigned_to="codex",
        sequence_order=1,
    )
    in_progress_task_id = await insert_task(
        db_pool,
        title="Current task",
        milestone_id=milestone_id,
        status="in_progress",
        assigned_to="codex",
        sequence_order=2,
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["id"] == in_progress_task_id
    assert task["status"] == "in_progress"


async def test_get_current_task_falls_back_to_open(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Core")
    task_id = await insert_task(
        db_pool,
        title="Assigned open task",
        milestone_id=milestone_id,
        status="open",
        assigned_to="codex",
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["id"] == task_id
    assert task["status"] == "open"


async def test_get_current_task_none(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Core")
    await insert_task(
        db_pool,
        title="Other agent task",
        milestone_id=milestone_id,
        status="open",
        assigned_to="claude",
    )

    assert await tasks.get_current_task("codex") is None


async def test_get_current_task_includes_milestone_info(db_pool):
    milestone_id = await insert_milestone(
        db_pool,
        name="Planner",
        description="Planning work",
    )
    await insert_task(
        db_pool,
        title="Named milestone task",
        milestone_id=milestone_id,
        status="in_progress",
        assigned_to="codex",
    )

    task = await tasks.get_current_task("codex")

    assert task is not None
    assert task["milestone_name"] == "Planner"
    assert task["milestone_description"] == "Planning work"


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
    high_priority_milestone = await insert_milestone(db_pool, name="Urgent", priority=10)
    lower_priority_milestone = await insert_milestone(db_pool, name="Assigned", priority=1)
    await insert_task(
        db_pool,
        title="Unassigned urgent",
        milestone_id=high_priority_milestone,
        status="open",
        assigned_to=None,
        sequence_order=1,
    )
    assigned_task_id = await insert_task(
        db_pool,
        title="Assigned open",
        milestone_id=lower_priority_milestone,
        status="open",
        assigned_to="codex",
        sequence_order=5,
    )

    task = await tasks.get_next_task("codex")

    assert task is not None
    assert task["id"] == assigned_task_id
    assert task["assigned_to"] == "codex"


async def test_get_next_task_falls_back_unassigned(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Shared", priority=7)
    task_id = await insert_task(
        db_pool,
        title="Shared task",
        milestone_id=milestone_id,
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
    milestone_id = await insert_milestone(
        db_pool,
        name="Build",
        description="Build tasks",
        priority=5,
    )
    task_id = await insert_task(
        db_pool,
        title="Claim me",
        milestone_id=milestone_id,
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
    assert task["milestone_name"] == "Build"
    assert task["milestone_description"] == "Build tasks"
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
    assert row[:9] == (milestone_id, "Claim me", None, "in_progress", 0, "codex", [], [], [])


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
    assert row[:9] == (None, "Release me", None, "open", 0, None, [], [], [])


async def test_list_tasks_no_filter(db_pool):
    lower_milestone_id = await insert_milestone(
        db_pool,
        name="Lower",
        description="Lower priority",
        priority=1,
    )
    higher_milestone_id = await insert_milestone(
        db_pool,
        name="Higher",
        description="Higher priority",
        priority=9,
    )
    first_id = await insert_task(
        db_pool,
        title="Higher first",
        milestone_id=higher_milestone_id,
        sequence_order=1,
    )
    second_id = await insert_task(
        db_pool,
        title="Higher second",
        milestone_id=higher_milestone_id,
        sequence_order=2,
    )
    third_id = await insert_task(
        db_pool,
        title="Lower only",
        milestone_id=lower_milestone_id,
        sequence_order=1,
    )

    result = await tasks.list_tasks()

    assert [task["id"] for task in result] == [first_id, second_id, third_id]
    assert result[0]["milestone_name"] == "Higher"
    assert result[0]["milestone_description"] == "Higher priority"
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


async def test_list_tasks_by_tag(db_pool):
    tagged_id = await insert_task(
        db_pool,
        title="Orchestrator task",
        tags=["orchestrator"],
    )
    await insert_task(db_pool, title="Memory task", tags=["memory"])

    result = await tasks.list_tasks(tag="orchestrator")

    assert [task["id"] for task in result] == [tagged_id]
    assert result[0]["tags"] == ["orchestrator"]


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
        "milestone_id": None,
        "milestone_name": None,
        "milestone_description": None,
        "github_issues": [],
        "tags": [],
        "relevant_docs": [],
        "sequence_order": 0,
        "depends_on": [],
    }
    assert row[:9] == (None, "Minimal task", None, "open", 0, None, [], [], [])


async def test_create_task_with_tags_and_issues(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Phase 3")
    task = await tasks.create_task(
        "Tagged task",
        milestone_id=milestone_id,
        github_issues=[143, 147],
        tags=["orchestrator", "salience"],
    )

    assert task["milestone_id"] == milestone_id
    assert task["github_issues"] == [143, 147]
    assert task["tags"] == ["orchestrator", "salience"]


async def test_create_task_with_depends_on(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency")
    task = await tasks.create_task("Dependent", depends_on=[dep_id])

    assert task["depends_on"] == [dep_id]


async def test_get_next_task_skips_unmet_deps(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency", status="open")
    await insert_task(
        db_pool, title="Blocked by dep", status="open", depends_on=[dep_id]
    )

    # The only open task without unmet deps is the dependency itself
    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dep_id


async def test_get_next_task_returns_task_when_deps_met(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency", status="done")
    dependent_id = await insert_task(
        db_pool, title="Ready to go", status="open", depends_on=[dep_id]
    )

    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dependent_id


async def test_get_next_task_cancelled_dep_counts_as_met(db_pool):
    dep_id = await insert_task(db_pool, title="Cancelled dep", status="cancelled")
    dependent_id = await insert_task(
        db_pool, title="Unblocked", status="open", depends_on=[dep_id]
    )

    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dependent_id


async def test_get_next_task_multiple_deps_all_must_be_met(db_pool):
    dep1_id = await insert_task(db_pool, title="Done dep", status="done")
    dep2_id = await insert_task(db_pool, title="Open dep", status="open")
    await insert_task(
        db_pool,
        title="Needs both",
        status="open",
        depends_on=[dep1_id, dep2_id],
    )

    # Only dep2 should be returned (dep1 is done, dependent is blocked)
    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dep2_id


async def test_claim_task_with_unmet_deps_fails(db_pool):
    dep_id = await insert_task(db_pool, title="Not done", status="open")
    dependent_id = await insert_task(
        db_pool, title="Blocked", status="open", depends_on=[dep_id]
    )

    with pytest.raises(ValueError, match="unmet dependencies"):
        await tasks.claim_task(dependent_id, "codex")


async def test_claim_task_with_met_deps_succeeds(db_pool):
    dep_id = await insert_task(db_pool, title="Done", status="done")
    dependent_id = await insert_task(
        db_pool, title="Ready", status="open", depends_on=[dep_id]
    )

    task = await tasks.claim_task(dependent_id, "codex")
    assert task["id"] == dependent_id
    assert task["status"] == "in_progress"


async def test_claim_task_unmet_deps_error_lists_blockers(db_pool):
    dep1_id = await insert_task(db_pool, title="Blocker 1", status="in_progress")
    dep2_id = await insert_task(db_pool, title="Blocker 2", status="open")
    dependent_id = await insert_task(
        db_pool,
        title="Blocked",
        status="open",
        depends_on=[dep1_id, dep2_id],
    )

    with pytest.raises(ValueError, match=f"#{dep1_id}") as exc_info:
        await tasks.claim_task(dependent_id, "codex")
    assert f"#{dep2_id}" in str(exc_info.value)


async def test_parallel_tasks_both_claimable(db_pool):
    """Tasks with same dependency but no relationship to each other are parallel."""
    dep_id = await insert_task(db_pool, title="Setup", status="done")
    task_a_id = await insert_task(
        db_pool, title="Task A", status="open", depends_on=[dep_id]
    )
    task_b_id = await insert_task(
        db_pool, title="Task B", status="open", depends_on=[dep_id]
    )

    task_a = await tasks.claim_task(task_a_id, "codex")
    task_b = await tasks.claim_task(task_b_id, "claude")

    assert task_a["status"] == "in_progress"
    assert task_b["status"] == "in_progress"


async def test_no_deps_field_defaults_empty(db_pool):
    task_id = await insert_task(db_pool, title="No deps")
    task = await tasks.claim_task(task_id, "codex")

    assert task["depends_on"] == []
