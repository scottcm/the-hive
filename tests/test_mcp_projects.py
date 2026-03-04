import pytest

from coordinator.mcp.tools import projects


async def insert_project(
    db_pool,
    *,
    name: str,
    description: str | None = None,
    status: str = "active",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.projects (name, description, status)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, description, status),
        )
        return (await cursor.fetchone())[0]


async def insert_milestone(
    db_pool,
    *,
    name: str,
    project_id: int | None = None,
    priority: int = 0,
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.milestones (name, priority, project_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (name, priority, project_id),
        )
        return (await cursor.fetchone())[0]


async def insert_task(
    db_pool,
    *,
    title: str,
    milestone_id: int,
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


async def test_list_projects_empty(db_pool):
    assert await projects.list_projects() == []


async def test_create_project_minimal(db_pool):
    project = await projects.create_project("GLADyS")

    assert project == {
        "id": project["id"],
        "name": "GLADyS",
        "description": None,
        "status": "active",
        "milestone_count": 0,
        "task_counts": {"open": 0, "in_progress": 0, "blocked": 0, "done": 0},
    }


async def test_create_project_full(db_pool):
    project = await projects.create_project(
        "the-hive",
        description="Work coordination system",
    )

    assert project["name"] == "the-hive"
    assert project["description"] == "Work coordination system"


async def test_list_projects_with_counts(db_pool):
    project_id = await insert_project(db_pool, name="GLADyS")
    milestone_id = await insert_milestone(db_pool, name="Phase 3", project_id=project_id)
    await insert_task(db_pool, title="Open", milestone_id=milestone_id, status="open")
    await insert_task(db_pool, title="WIP", milestone_id=milestone_id, status="in_progress")
    await insert_task(db_pool, title="Done", milestone_id=milestone_id, status="done")

    result = await projects.list_projects()

    assert len(result) == 1
    assert result[0]["milestone_count"] == 1
    assert result[0]["task_counts"] == {
        "open": 1,
        "in_progress": 1,
        "blocked": 0,
        "done": 1,
    }


async def test_list_projects_filter_by_status(db_pool):
    active_id = await insert_project(db_pool, name="Active", status="active")
    await insert_project(db_pool, name="Archived", status="archived")

    result = await projects.list_projects(status="active")

    assert [p["id"] for p in result] == [active_id]


async def test_list_projects_ordered_by_name(db_pool):
    await insert_project(db_pool, name="Zebra")
    await insert_project(db_pool, name="Alpha")

    result = await projects.list_projects()

    assert [p["name"] for p in result] == ["Alpha", "Zebra"]


async def test_update_project(db_pool):
    project_id = await insert_project(db_pool, name="Old")

    project = await projects.update_project(
        project_id,
        name="New",
        description="Updated",
        status="archived",
    )

    assert project["name"] == "New"
    assert project["description"] == "Updated"
    assert project["status"] == "archived"


async def test_update_project_not_found(db_pool):
    with pytest.raises(ValueError, match="Project 9999 not found"):
        await projects.update_project(9999, name="Nope")
