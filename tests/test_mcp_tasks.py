from datetime import datetime, timedelta, timezone

import pytest

from coordinator.mcp.tools import evidence, tasks


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


async def insert_task_contract(
    db_pool,
    *,
    task_id: int,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    dependencies: list[int] | None = None,
    red_tests: list[str] | None = None,
    green_tests: list[str] | None = None,
    min_reviews: int = 1,
    independent_required: bool = True,
    handoff_template: str = "v1_task_handoff",
) -> None:
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO hive.task_contracts (
                task_id,
                contract_version,
                allowed_paths,
                forbidden_paths,
                dependencies,
                required_tests,
                review_policy,
                handoff_template
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            """,
            (
                task_id,
                1,
                allowed_paths or ["coordinator/**"],
                forbidden_paths or [],
                dependencies or [],
                (
                    '{"red": ["pytest tests/test_mcp_tasks.py -k claim"], '
                    '"green": ["pytest tests/test_mcp_tasks.py -k claim"]}'
                    if red_tests is None and green_tests is None
                    else (
                        '{"red": ['
                        + ", ".join(f'"{cmd}"' for cmd in (red_tests or []))
                        + '], "green": ['
                        + ", ".join(f'"{cmd}"' for cmd in (green_tests or []))
                        + "]}"
                    )
                ),
                (
                    '{"min_reviews": '
                    + str(min_reviews)
                    + ', "independent_required": '
                    + ("true" if independent_required else "false")
                    + "}"
                ),
                handoff_template,
            ),
        )


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


async def fetch_gate_events(db_pool, task_id: int) -> list[tuple]:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT gate_name, decision
            FROM hive.task_gate_events
            WHERE task_id = %s
            ORDER BY id
            """,
            (task_id,),
        )
        return await cursor.fetchall()


async def insert_task_override(
    db_pool,
    *,
    task_id: int,
    gate_name: str,
    approved_by: str = "owner",
    reason: str = "approved exception",
    expires_at: datetime | None = None,
) -> None:
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    async with db_pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO hive.task_overrides (
                task_id,
                gate_name,
                scope,
                approved_by,
                reason,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                task_id,
                gate_name,
                "status_transition",
                approved_by,
                reason,
                expires_at,
            ),
        )


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
    unassigned_task_id = await insert_task(
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
    await insert_task_contract(db_pool, task_id=unassigned_task_id, dependencies=[])
    await insert_task_contract(db_pool, task_id=assigned_task_id, dependencies=[])

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
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])

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
    await insert_task_contract(db_pool, task_id=task_id)

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
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])
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

    assert task["id"] is not None
    assert task["title"] == "Minimal task"
    assert task["description"] is None
    assert task["status"] == "open"
    assert task["assigned_to"] is None
    assert task["milestone_id"] is None
    assert task["github_issues"] == []
    assert task["tags"] == []
    assert task["relevant_docs"] == []
    assert task["sequence_order"] == 0
    assert task["depends_on"] == []
    assert task["created_at"] is not None
    assert task["updated_at"] is not None
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
    blocked_id = await insert_task(
        db_pool, title="Blocked by dep", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(db_pool, task_id=dep_id, dependencies=[])
    await insert_task_contract(db_pool, task_id=blocked_id, dependencies=[dep_id])

    # The only open task without unmet deps is the dependency itself
    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dep_id


async def test_get_next_task_returns_task_when_deps_met(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency", status="done")
    dependent_id = await insert_task(
        db_pool, title="Ready to go", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(db_pool, task_id=dependent_id, dependencies=[dep_id])

    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dependent_id


async def test_get_next_task_cancelled_dep_counts_as_met(db_pool):
    dep_id = await insert_task(db_pool, title="Cancelled dep", status="cancelled")
    dependent_id = await insert_task(
        db_pool, title="Unblocked", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(db_pool, task_id=dependent_id, dependencies=[dep_id])

    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dependent_id


async def test_get_next_task_multiple_deps_all_must_be_met(db_pool):
    dep1_id = await insert_task(db_pool, title="Done dep", status="done")
    dep2_id = await insert_task(db_pool, title="Open dep", status="open")
    dependent_id = await insert_task(
        db_pool,
        title="Needs both",
        status="open",
        depends_on=[dep1_id, dep2_id],
    )
    await insert_task_contract(db_pool, task_id=dep2_id, dependencies=[])
    await insert_task_contract(
        db_pool,
        task_id=dependent_id,
        dependencies=[dep1_id, dep2_id],
    )

    # Only dep2 should be returned (dep1 is done, dependent is blocked)
    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == dep2_id


async def test_get_next_task_skips_open_tasks_missing_contract(db_pool):
    missing_contract_id = await insert_task(
        db_pool,
        title="No contract",
        status="open",
        sequence_order=0,
    )
    claimable_id = await insert_task(
        db_pool,
        title="Has contract",
        status="open",
        sequence_order=1,
    )
    await insert_task_contract(db_pool, task_id=claimable_id, dependencies=[])

    task = await tasks.get_next_task("codex")
    assert task is not None
    assert task["id"] == claimable_id
    assert task["id"] != missing_contract_id


async def test_claim_task_with_unmet_deps_fails(db_pool):
    dep_id = await insert_task(db_pool, title="Not done", status="open")
    dependent_id = await insert_task(
        db_pool, title="Blocked", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(
        db_pool,
        task_id=dependent_id,
        dependencies=[dep_id],
    )

    with pytest.raises(ValueError, match="unmet dependencies"):
        await tasks.claim_task(dependent_id, "codex")


async def test_claim_task_with_met_deps_succeeds(db_pool):
    dep_id = await insert_task(db_pool, title="Done", status="done")
    dependent_id = await insert_task(
        db_pool, title="Ready", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(
        db_pool,
        task_id=dependent_id,
        dependencies=[dep_id],
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
    await insert_task_contract(
        db_pool,
        task_id=dependent_id,
        dependencies=[dep1_id, dep2_id],
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
    await insert_task_contract(
        db_pool,
        task_id=task_a_id,
        dependencies=[dep_id],
    )
    await insert_task_contract(
        db_pool,
        task_id=task_b_id,
        dependencies=[dep_id],
    )

    task_a = await tasks.claim_task(task_a_id, "codex")
    task_b = await tasks.claim_task(task_b_id, "claude")

    assert task_a["status"] == "in_progress"
    assert task_b["status"] == "in_progress"


async def test_no_deps_field_defaults_empty(db_pool):
    task_id = await insert_task(db_pool, title="No deps")
    await insert_task_contract(db_pool, task_id=task_id)
    task = await tasks.claim_task(task_id, "codex")

    assert task["depends_on"] == []


async def test_claim_task_requires_contract(db_pool):
    task_id = await insert_task(db_pool, title="No contract", status="open")

    with pytest.raises(ValueError, match="missing required task contract"):
        await tasks.claim_task(task_id, "codex")


async def test_release_task_rejects_blocked(db_pool):
    task_id = await insert_task(
        db_pool, title="Blocked task", status="blocked", assigned_to="codex"
    )

    with pytest.raises(ValueError, match="cannot be released"):
        await tasks.release_task(task_id)


async def test_release_task_rejects_done(db_pool):
    task_id = await insert_task(
        db_pool, title="Done task", status="done", assigned_to="codex"
    )

    with pytest.raises(ValueError, match="cannot be released"):
        await tasks.release_task(task_id)


async def test_release_task_rejects_open(db_pool):
    task_id = await insert_task(db_pool, title="Open task", status="open")

    with pytest.raises(ValueError, match="cannot be released"):
        await tasks.release_task(task_id)


async def test_release_task_not_found(db_pool):
    with pytest.raises(ValueError, match="not found"):
        await tasks.release_task(9999)


async def test_get_task_returns_full_shape(db_pool):
    milestone_id = await insert_milestone(
        db_pool, name="Test Milestone", description="For get_task"
    )
    task_id = await insert_task(
        db_pool,
        title="Full shape task",
        milestone_id=milestone_id,
        status="in_progress",
        assigned_to="codex",
    )
    note_id = await insert_note(
        db_pool, task_id=task_id, author="scott", content="A note"
    )
    clar_id = await insert_clarification(
        db_pool, task_id=task_id, asked_by="codex", question="Pending?"
    )

    task = await tasks.get_task(task_id)

    assert task["id"] == task_id
    assert task["title"] == "Full shape task"
    assert task["milestone_name"] == "Test Milestone"
    assert task["notes"][0]["id"] == note_id
    assert task["pending_clarifications"][0]["id"] == clar_id


async def test_get_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.get_task(9999)


async def test_set_task_contract_round_trip(db_pool):
    task_id = await insert_task(db_pool, title="Contracted task", status="open")

    contract = await tasks.set_task_contract(
        task_id=task_id,
        allowed_paths=["coordinator/**", "tests/**"],
        forbidden_paths=["dashboard/**"],
        dependencies=[],
        required_tests={
            "red": ["pytest tests/test_mcp_tasks.py -k contract"],
            "green": ["pytest tests/test_mcp_tasks.py -k contract -v"],
        },
        review_policy={"min_reviews": 1, "independent_required": True},
        handoff_template="v1_task_handoff",
    )

    fetched = await tasks.get_task_contract(task_id)

    assert contract["task_id"] == task_id
    assert contract["allowed_paths"] == ["coordinator/**", "tests/**"]
    assert contract["forbidden_paths"] == ["dashboard/**"]
    assert contract["required_tests"]["red"] == [
        "pytest tests/test_mcp_tasks.py -k contract"
    ]
    assert fetched == contract


async def test_set_task_contract_defaults_dependencies_to_task_depends_on(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency", status="done")
    task_id = await insert_task(
        db_pool,
        title="Contract inherits deps",
        status="open",
        depends_on=[dep_id],
    )

    contract = await tasks.set_task_contract(
        task_id=task_id,
        allowed_paths=["coordinator/**"],
    )

    assert contract["dependencies"] == [dep_id]

    task = await tasks.claim_task(task_id, "codex")
    assert task["id"] == task_id
    assert task["status"] == "in_progress"


async def test_set_task_contract_rejects_invalid_payload(db_pool):
    task_id = await insert_task(db_pool, title="Invalid contract", status="open")

    with pytest.raises(ValueError, match="required_tests.green"):
        await tasks.set_task_contract(
            task_id=task_id,
            allowed_paths=["coordinator/**"],
            required_tests={"red": ["pytest tests/ -k red"], "green": []},
            review_policy={"min_reviews": 1, "independent_required": True},
        )


async def test_update_task_done_requires_handoff_gate(db_pool):
    task_id = await insert_task(db_pool, title="Gate target", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["uv run pytest tests/test_mcp_tasks.py -k gate -v"],
        green_tests=["uv run pytest tests/test_mcp_tasks.py -k gate -v"],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="1" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_gate"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="2" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="3" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={
            "command": "uv run pytest tests/test_mcp_tasks.py -k gate -v",
            "passed": True,
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="4" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )

    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_records_gate_passes(db_pool):
    task_id = await insert_task(db_pool, title="Gate pass", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["uv run pytest tests/test_mcp_tasks.py -k gate-pass -v"],
        green_tests=["uv run pytest tests/test_mcp_tasks.py -k gate-pass -v"],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="5" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_gate_pass"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="6" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="7" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={
            "command": "uv run pytest tests/test_mcp_tasks.py -k gate-pass -v",
            "passed": True,
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="8" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="9" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Implemented gate engine.",
            "why_changed": "Enforce reliability policy.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run independent review"],
        },
    )

    task = await tasks.update_task(task_id=task_id, status="done")
    events = await fetch_gate_events(db_pool, task_id)

    assert task["status"] == "done"
    assert events == [
        ("G1_scope_lock", "pass"),
        ("G2_tdd_order", "pass"),
        ("G3_verification", "pass"),
        ("G4_review_separation", "pass"),
        ("G5_handoff_completeness", "pass"),
    ]


async def test_update_task_done_rejects_self_review(db_pool):
    task_id = await insert_task(db_pool, title="Self review", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="a" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_self_review"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="b" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="c" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={"command": "pytest tests/ -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="d" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="codex",
        metadata={"author": "codex", "reviewer": "codex"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="e" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Implemented gate engine.",
            "why_changed": "Enforce reliability policy.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run independent review"],
        },
    )

    with pytest.raises(ValueError, match="G4"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_accepts_mixed_reviews_with_one_independent(db_pool):
    task_id = await insert_task(db_pool, title="Mixed reviews", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/test_mcp_tasks.py -k mixed-review -v"],
        green_tests=["pytest tests/test_mcp_tasks.py -k mixed-review -v"],
        min_reviews=2,
        independent_required=True,
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="f" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_mixed_review"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="1" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="2" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={
            "command": "pytest tests/test_mcp_tasks.py -k mixed-review -v",
            "passed": True,
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="3" * 64,
        storage_ref="file://artifacts/review-1.md",
        captured_by="codex",
        metadata={"author": "codex", "reviewer": "codex"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="4" * 64,
        storage_ref="file://artifacts/review-2.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="5" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Implemented gate engine.",
            "why_changed": "Enforce reliability policy.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run independent review"],
        },
    )

    task = await tasks.update_task(task_id=task_id, status="done")

    assert task["status"] == "done"


async def test_update_task_done_allows_self_review_when_independence_not_required(
    db_pool,
):
    task_id = await insert_task(
        db_pool, title="Self review allowed by policy", status="in_progress"
    )
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/test_mcp_tasks.py -k independent-false -v"],
        green_tests=["pytest tests/test_mcp_tasks.py -k independent-false -v"],
        min_reviews=1,
        independent_required=False,
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="6" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={
            "failing_tests": ["tests/test_mcp_tasks.py::test_independent_required_false"]
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="7" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="8" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={
            "command": "pytest tests/test_mcp_tasks.py -k independent-false -v",
            "passed": True,
        },
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="9" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="codex",
        metadata={"author": "codex", "reviewer": "codex"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="a" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Adjusted review policy behavior.",
            "why_changed": "Independent review is disabled for this contract.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Re-enable independent review policy when needed"],
        },
    )

    task = await tasks.update_task(task_id=task_id, status="done")
    events = await fetch_gate_events(db_pool, task_id)

    assert task["status"] == "done"
    assert ("G4_review_separation", "pass") in events


async def test_update_task_in_progress_requires_contract(db_pool):
    task_id = await insert_task(db_pool, title="Start without contract", status="open")

    with pytest.raises(ValueError, match="missing required task contract"):
        await tasks.update_task(task_id=task_id, status="in_progress")


async def test_update_task_in_progress_rejects_unmet_dependencies(db_pool):
    dep_id = await insert_task(db_pool, title="Dependency", status="open")
    task_id = await insert_task(
        db_pool,
        title="Blocked start",
        status="open",
        depends_on=[dep_id],
    )
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        dependencies=[dep_id],
    )

    with pytest.raises(ValueError, match="unmet dependencies"):
        await tasks.update_task(task_id=task_id, status="in_progress")


async def test_update_task_done_allows_gate_override(db_pool):
    task_id = await insert_task(db_pool, title="Override handoff", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/test_mcp_tasks.py -k override -v"],
        green_tests=["pytest tests/test_mcp_tasks.py -k override -v"],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="f" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_override"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="1" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="2" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={"command": "pytest tests/test_mcp_tasks.py -k override -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="3" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await insert_task_override(
        db_pool,
        task_id=task_id,
        gate_name="G5_handoff_completeness",
    )

    task = await tasks.update_task(task_id=task_id, status="done")
    events = await fetch_gate_events(db_pool, task_id)

    assert task["status"] == "done"
    assert ("G5_handoff_completeness", "override") in events


async def test_update_task_done_rejects_expired_override(db_pool):
    task_id = await insert_task(db_pool, title="Expired override", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/test_mcp_tasks.py -k expired -v"],
        green_tests=["pytest tests/test_mcp_tasks.py -k expired -v"],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="4" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_expired_override"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="5" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="6" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={"command": "pytest tests/test_mcp_tasks.py -k expired -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="7" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await insert_task_override(
        db_pool,
        task_id=task_id,
        gate_name="G5_handoff_completeness",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_requires_red_before_implementation(db_pool):
    task_id = await insert_task(db_pool, title="TDD strict ordering", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/test_mcp_tasks.py -k tdd-order -v"],
        green_tests=["pytest tests/test_mcp_tasks.py -k tdd-order -v"],
    )
    same_time = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc).isoformat()
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="8" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="codex",
        captured_at=same_time,
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_tdd_order"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="9" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="codex",
        captured_at=same_time,
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="a" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="codex",
        metadata={"command": "pytest tests/test_mcp_tasks.py -k tdd-order -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="b" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="claude",
        metadata={"author": "codex", "reviewer": "claude"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="c" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="codex",
        metadata={
            "what_changed": "Gate logic updates.",
            "why_changed": "Enforce strict TDD ordering.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run review"],
        },
    )

    with pytest.raises(ValueError, match="G2"):
        await tasks.update_task(task_id=task_id, status="done")


async def _setup_task_with_handoff(db_pool, handoff_metadata: dict) -> int:
    """Helper: create a fully-evidenced task with a custom handoff payload."""
    task_id = await insert_task(db_pool, title="Handoff schema task", status="in_progress")
    await insert_task_contract(
        db_pool,
        task_id=task_id,
        allowed_paths=["coordinator/**"],
        dependencies=[],
        red_tests=["pytest tests/ -k handoff-schema -v"],
        green_tests=["pytest tests/ -k handoff-schema -v"],
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="red_run",
        artifact_hash_sha256="1" * 64,
        storage_ref="file://artifacts/red.log",
        captured_by="claude-scott",
        metadata={"failing_tests": ["tests/test_mcp_tasks.py::test_handoff_schema"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="implementation_commit",
        artifact_hash_sha256="2" * 64,
        storage_ref="file://artifacts/commit.json",
        captured_by="claude-scott",
        metadata={"changed_files": ["coordinator/mcp/tools/tasks.py"]},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="green_run",
        artifact_hash_sha256="3" * 64,
        storage_ref="file://artifacts/green.log",
        captured_by="claude-scott",
        metadata={"command": "pytest tests/ -k handoff-schema -v", "passed": True},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="review_output",
        artifact_hash_sha256="4" * 64,
        storage_ref="file://artifacts/review.md",
        captured_by="reviewer-x",
        metadata={"author": "claude-scott", "reviewer": "reviewer-x"},
    )
    await evidence.record_task_evidence(
        task_id=task_id,
        artifact_type="handoff_packet",
        artifact_hash_sha256="5" * 64,
        storage_ref="file://artifacts/handoff.json",
        captured_by="claude-scott",
        metadata=handoff_metadata,
    )
    return task_id


async def test_update_task_done_rejects_handoff_with_wrong_field_types(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": "Added schema validation.",
            "why_changed": "Enforce type integrity.",
            "residual_risks": "none",  # should be list
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run review"],
        },
    )
    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_rejects_handoff_with_string_fields_as_list(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": ["Added schema validation."],  # should be str
            "why_changed": "Enforce type integrity.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run review"],
        },
    )
    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_accepts_valid_handoff_schema(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": "Added schema validation.",
            "why_changed": "Enforce type integrity.",
            "residual_risks": ["Risk A"],
            "unresolved_questions": [],
            "verification_links": ["file://artifacts/green.log"],
            "next_actions": ["Run review"],
        },
    )
    task = await tasks.update_task(task_id=task_id, status="done")
    assert task["status"] == "done"


async def test_update_task_done_rejects_handoff_with_empty_verification_links(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": "Added schema validation.",
            "why_changed": "Enforce type integrity.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": [],  # empty — no usable evidence link
            "next_actions": ["Run review"],
        },
    )
    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_rejects_handoff_with_non_string_verification_link(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": "Added schema validation.",
            "why_changed": "Enforce type integrity.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": [123],  # non-string entry
            "next_actions": ["Run review"],
        },
    )
    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_done_rejects_handoff_with_blank_verification_link(db_pool):
    task_id = await _setup_task_with_handoff(
        db_pool,
        {
            "what_changed": "Added schema validation.",
            "why_changed": "Enforce type integrity.",
            "residual_risks": [],
            "unresolved_questions": [],
            "verification_links": [""],  # blank string — not a usable link
            "next_actions": ["Run review"],
        },
    )
    with pytest.raises(ValueError, match="G5"):
        await tasks.update_task(task_id=task_id, status="done")


# ---------------------------------------------------------------------------
# superseded status
# ---------------------------------------------------------------------------


async def test_superseded_is_valid_status(db_pool):
    task_id = await insert_task(db_pool, title="Will be superseded", status="in_progress")
    task = await tasks.update_task(task_id=task_id, status="superseded")
    assert task["status"] == "superseded"


# ---------------------------------------------------------------------------
# list_gate_events
# ---------------------------------------------------------------------------


async def insert_gate_event(
    db_pool,
    *,
    task_id: int,
    gate_name: str = "G1_scope_lock",
    decision: str = "fail",
    reason: str = "test reason",
    actor: str = "test-actor",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.task_gate_events (task_id, gate_name, decision, reason, actor)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (task_id, gate_name, decision, reason, actor),
        )
        return (await cursor.fetchone())[0]


async def test_list_gate_events_returns_events_for_task(db_pool):
    task_id = await insert_task(db_pool, title="Gate event task", status="in_progress")
    await insert_gate_event(db_pool, task_id=task_id, gate_name="G1_scope_lock", decision="fail")

    events = await tasks.list_gate_events(task_id)
    assert len(events) == 1
    assert all(e["task_id"] == task_id for e in events)
    event = events[0]
    assert "id" in event
    assert "gate_name" in event
    assert "decision" in event
    assert "reason" in event
    assert "actor" in event
    assert "created_at" in event


async def test_list_gate_events_filter_by_gate_name(db_pool):
    task_id = await insert_task(db_pool, title="Gate filter task", status="in_progress")
    await insert_gate_event(db_pool, task_id=task_id, gate_name="G1_scope_lock", decision="fail")
    await insert_gate_event(db_pool, task_id=task_id, gate_name="G2_tdd_order", decision="pass")

    filtered = await tasks.list_gate_events(task_id, gate_name="G1_scope_lock")
    assert len(filtered) == 1
    assert filtered[0]["gate_name"] == "G1_scope_lock"


async def test_list_gate_events_filter_by_decision(db_pool):
    task_id = await insert_task(db_pool, title="Decision filter task", status="in_progress")
    await insert_gate_event(db_pool, task_id=task_id, gate_name="G1_scope_lock", decision="fail")
    await insert_gate_event(db_pool, task_id=task_id, gate_name="G2_tdd_order", decision="pass")

    fail_events = await tasks.list_gate_events(task_id, decision="fail")
    assert len(fail_events) == 1
    assert all(e["decision"] == "fail" for e in fail_events)


async def test_list_gate_events_empty_for_new_task(db_pool):
    task_id = await insert_task(db_pool, title="No gate events", status="open")
    events = await tasks.list_gate_events(task_id)
    assert events == []


async def test_list_gate_events_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.list_gate_events(9999)


# ---------------------------------------------------------------------------
# expire_override
# ---------------------------------------------------------------------------


async def test_expire_override_makes_override_inactive(db_pool):
    task_id = await insert_task(db_pool, title="Override task", status="in_progress")
    await insert_task_override(db_pool, task_id=task_id, gate_name="G1_scope_lock")

    overrides_before = await tasks.list_task_overrides(task_id)
    assert len(overrides_before) == 1
    override_id = overrides_before[0]["id"]

    result = await tasks.expire_override(
        override_id, actor="claude-scott", reason="no longer needed"
    )

    assert result["id"] == override_id
    overrides_after = await tasks.list_task_overrides(task_id)
    assert len(overrides_after) == 0


async def test_expire_override_not_found(db_pool):
    with pytest.raises(ValueError, match="Override 9999 not found"):
        await tasks.expire_override(9999, actor="claude-scott", reason="test")


# ---------------------------------------------------------------------------
# reopen_task
# ---------------------------------------------------------------------------


async def test_reopen_task_from_done(db_pool):
    task_id = await insert_task(db_pool, title="Done task", status="done")
    task = await tasks.reopen_task(task_id, actor="claude-scott", reason="needs more work")
    assert task["status"] == "open"


async def test_reopen_task_from_cancelled(db_pool):
    task_id = await insert_task(db_pool, title="Cancelled task", status="cancelled")
    task = await tasks.reopen_task(task_id, actor="claude-scott", reason="reactivated")
    assert task["status"] == "open"


async def test_reopen_task_not_done_or_cancelled_fails(db_pool):
    task_id = await insert_task(db_pool, title="Open task", status="open")
    with pytest.raises(ValueError, match="reopen"):
        await tasks.reopen_task(task_id, actor="claude-scott", reason="bad request")


async def test_reopen_task_not_found(db_pool):
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.reopen_task(9999, actor="claude-scott", reason="test")


# ---------------------------------------------------------------------------
# supersede_task
# ---------------------------------------------------------------------------


async def test_supersede_task_marks_as_superseded(db_pool):
    original_id = await insert_task(db_pool, title="Original task", status="open")
    replacement_id = await insert_task(db_pool, title="Replacement task", status="open")

    task = await tasks.supersede_task(
        original_id,
        replacement_task_id=replacement_id,
        actor="claude-scott",
        reason="replaced by better task",
    )
    assert task["status"] == "superseded"


async def test_supersede_task_not_found(db_pool):
    replacement_id = await insert_task(db_pool, title="Replacement", status="open")
    with pytest.raises(ValueError, match="Task 9999 not found"):
        await tasks.supersede_task(
            9999, replacement_task_id=replacement_id, actor="a", reason="r"
        )


async def test_supersede_task_replacement_not_found(db_pool):
    original_id = await insert_task(db_pool, title="Original", status="open")
    with pytest.raises(ValueError, match="9999 not found"):
        await tasks.supersede_task(
            original_id, replacement_task_id=9999, actor="a", reason="r"
        )


# ---------------------------------------------------------------------------
# validate_task_contract
# ---------------------------------------------------------------------------


async def test_validate_task_contract_returns_gate_results(db_pool):
    task_id = await insert_task(db_pool, title="Validate contract task", status="in_progress")
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])

    result = await tasks.validate_task_contract(task_id)

    assert "gates" in result
    assert isinstance(result["gates"], list)
    assert len(result["gates"]) > 0
    gate = result["gates"][0]
    assert "gate_name" in gate
    assert "decision" in gate
    assert "reason" in gate


async def test_validate_task_contract_does_not_record_events(db_pool):
    task_id = await insert_task(db_pool, title="Dry run task", status="in_progress")
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])

    await tasks.validate_task_contract(task_id)

    events = await fetch_gate_events(db_pool, task_id)
    assert events == []


async def test_validate_task_contract_no_contract_fails(db_pool):
    task_id = await insert_task(db_pool, title="No contract task", status="in_progress")
    with pytest.raises(ValueError, match="contract"):
        await tasks.validate_task_contract(task_id)


# ---------------------------------------------------------------------------
# Transition matrix guards in update_task
# ---------------------------------------------------------------------------


async def test_update_task_rejects_done_to_in_progress(db_pool):
    task_id = await insert_task(db_pool, title="Done task", status="done")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="in_progress")


async def test_update_task_rejects_done_to_blocked(db_pool):
    task_id = await insert_task(db_pool, title="Done task 2", status="done")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="blocked")


async def test_update_task_rejects_cancelled_to_in_progress(db_pool):
    task_id = await insert_task(db_pool, title="Cancelled task", status="cancelled")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="in_progress")


async def test_update_task_rejects_superseded_to_open(db_pool):
    task_id = await insert_task(db_pool, title="Superseded task", status="superseded")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="open")


async def test_update_task_rejects_open_to_done(db_pool):
    task_id = await insert_task(db_pool, title="Open → done invalid", status="open")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_rejects_blocked_to_done(db_pool):
    task_id = await insert_task(db_pool, title="Blocked → done invalid", status="blocked")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="done")


async def test_update_task_allows_in_progress_to_blocked(db_pool):
    task_id = await insert_task(db_pool, title="IP → blocked valid", status="in_progress")
    task = await tasks.update_task(task_id=task_id, status="blocked")
    assert task["status"] == "blocked"


async def test_update_task_allows_in_progress_to_cancelled(db_pool):
    task_id = await insert_task(db_pool, title="IP → cancelled admin", status="in_progress")
    task = await tasks.update_task(task_id=task_id, status="cancelled")
    assert task["status"] == "cancelled"


async def test_update_task_allows_open_to_cancelled(db_pool):
    task_id = await insert_task(db_pool, title="Open → cancelled admin", status="open")
    task = await tasks.update_task(task_id=task_id, status="cancelled")
    assert task["status"] == "cancelled"


async def test_update_task_rejects_blocked_to_open(db_pool):
    """Finding 2: blocked→open removed; blocked tasks must go to in_progress."""
    task_id = await insert_task(db_pool, title="Blocked → open invalid", status="blocked")
    with pytest.raises(ValueError, match="transition"):
        await tasks.update_task(task_id=task_id, status="open")


# ---------------------------------------------------------------------------
# Gate event audit for non-done transitions (Finding 1 + 3)
# ---------------------------------------------------------------------------


async def test_claim_task_records_start_gate_pass_event(db_pool):
    task_id = await insert_task(db_pool, title="Claim gate event task", status="open")
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])

    await tasks.claim_task(task_id, "codex")

    events = await fetch_gate_events(db_pool, task_id)
    gate_names = [e[0] for e in events]
    assert "G_start_dependencies" in gate_names
    start_event = next(e for e in events if e[0] == "G_start_dependencies")
    assert start_event[1] == "pass"


async def test_update_task_to_in_progress_records_start_gate_event(db_pool):
    task_id = await insert_task(db_pool, title="Update IP gate event", status="open")
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[])

    await tasks.update_task(task_id=task_id, status="in_progress")

    events = await fetch_gate_events(db_pool, task_id)
    gate_names = [e[0] for e in events]
    assert "G_start_dependencies" in gate_names
    start_event = next(e for e in events if e[0] == "G_start_dependencies")
    assert start_event[1] == "pass"


async def test_claim_task_with_override_records_start_gate_override_event(db_pool):
    dep_id = await insert_task(db_pool, title="Unmet dep", status="open")
    task_id = await insert_task(
        db_pool, title="Override start", status="open", depends_on=[dep_id]
    )
    await insert_task_contract(db_pool, task_id=task_id, dependencies=[dep_id])
    await insert_task_override(db_pool, task_id=task_id, gate_name="G_start_dependencies")

    await tasks.claim_task(task_id, "codex")

    events = await fetch_gate_events(db_pool, task_id)
    start_event = next((e for e in events if e[0] == "G_start_dependencies"), None)
    assert start_event is not None
    assert start_event[1] == "override"
