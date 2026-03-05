import pytest

from coordinator.mcp.tools import milestones


async def insert_project(
    db_pool,
    *,
    name: str,
    description: str | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.projects (name, description)
            VALUES (%s, %s)
            RETURNING id
            """,
            (name, description),
        )
        return (await cursor.fetchone())[0]


async def insert_milestone(
    db_pool,
    *,
    name: str,
    description: str | None = None,
    priority: int = 0,
    status: str = "active",
    project_id: int | None = None,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.milestones (name, description, priority, status, project_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (name, description, priority, status, project_id),
        )
        return (await cursor.fetchone())[0]


async def insert_task(
    db_pool,
    *,
    title: str,
    milestone_id: int | None = None,
    status: str = "open",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (milestone_id, title, status, sequence_order, relevant_docs, tags, github_issues)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (milestone_id, title, status, 0, [], [], []),
        )
        return (await cursor.fetchone())[0]


async def fetch_milestone_row(db_pool, milestone_id: int) -> tuple:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT name, description, priority, status
            FROM hive.milestones
            WHERE id = %s
            """,
            (milestone_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row


async def test_list_milestones_empty(db_pool):
    assert await milestones.list_milestones() == []


async def test_list_milestones_with_counts(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Core", priority=4)
    await insert_task(db_pool, title="Open task", milestone_id=milestone_id, status="open")
    await insert_task(
        db_pool,
        title="In progress task",
        milestone_id=milestone_id,
        status="in_progress",
    )
    await insert_task(db_pool, title="Done task", milestone_id=milestone_id, status="done")
    await insert_task(db_pool, title="Blocked task", milestone_id=milestone_id, status="blocked")
    await insert_task(
        db_pool,
        title="Cancelled task",
        milestone_id=milestone_id,
        status="cancelled",
    )

    result = await milestones.list_milestones()

    assert result == [
        {
            "id": milestone_id,
            "project_id": None,
            "project_name": None,
            "name": "Core",
            "description": None,
            "priority": 4,
            "status": "active",
            "task_counts": {
                "open": 1,
                "in_progress": 1,
                "done": 1,
                "blocked": 1,
            },
        }
    ]


async def test_list_milestones_filter_by_status(db_pool):
    active_id = await insert_milestone(db_pool, name="Active", status="active")
    await insert_milestone(db_pool, name="Done", status="done")

    result = await milestones.list_milestones(status="active")

    assert [m["id"] for m in result] == [active_id]
    assert result[0]["status"] == "active"


async def test_list_milestones_filter_by_project(db_pool):
    project_id = await insert_project(db_pool, name="GLADyS")
    in_project = await insert_milestone(db_pool, name="Phase 3", project_id=project_id)
    await insert_milestone(db_pool, name="Orphan")

    result = await milestones.list_milestones(project_id=project_id)

    assert [m["id"] for m in result] == [in_project]
    assert result[0]["project_name"] == "GLADyS"


async def test_list_milestones_ordered_by_priority(db_pool):
    low_id = await insert_milestone(db_pool, name="Low", priority=1)
    high_id = await insert_milestone(db_pool, name="High", priority=9)
    mid_id = await insert_milestone(db_pool, name="Mid", priority=4)

    result = await milestones.list_milestones()

    assert [m["id"] for m in result] == [high_id, mid_id, low_id]


async def test_create_milestone_minimal(db_pool):
    milestone = await milestones.create_milestone("Planning")
    row = await fetch_milestone_row(db_pool, milestone["id"])

    assert milestone == {
        "id": milestone["id"],
        "project_id": None,
        "project_name": None,
        "name": "Planning",
        "description": None,
        "priority": 0,
        "status": "active",
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Planning", None, 0, "active")


async def test_create_milestone_with_project(db_pool):
    project_id = await insert_project(db_pool, name="GLADyS")
    milestone = await milestones.create_milestone(
        "Phase 4",
        project_id=project_id,
        priority=10,
    )

    assert milestone["project_id"] == project_id
    assert milestone["project_name"] == "GLADyS"


async def test_create_milestone_full(db_pool):
    milestone = await milestones.create_milestone(
        "Execution",
        description="Implementation work",
        priority=8,
    )
    row = await fetch_milestone_row(db_pool, milestone["id"])

    assert milestone == {
        "id": milestone["id"],
        "project_id": None,
        "project_name": None,
        "name": "Execution",
        "description": "Implementation work",
        "priority": 8,
        "status": "active",
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Execution", "Implementation work", 8, "active")


async def test_update_milestone_fields(db_pool):
    milestone_id = await insert_milestone(db_pool, name="Old", description="Before", priority=1)

    milestone = await milestones.update_milestone(
        milestone_id,
        name="New",
        priority=7,
        status="done",
    )
    row = await fetch_milestone_row(db_pool, milestone_id)

    assert milestone["id"] == milestone_id
    assert milestone["name"] == "New"
    assert milestone["description"] == "Before"
    assert milestone["priority"] == 7
    assert milestone["status"] == "done"
    assert row == ("New", "Before", 7, "done")


async def test_update_milestone_not_found(db_pool):
    with pytest.raises(ValueError, match="Milestone 9999 not found"):
        await milestones.update_milestone(9999, name="Nope")


async def test_create_milestone_invalid_project_id(db_pool):
    with pytest.raises(ValueError, match="Project 9999 not found"):
        await milestones.create_milestone("Bad project", project_id=9999)
