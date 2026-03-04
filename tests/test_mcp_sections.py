import pytest

from coordinator.mcp.tools import sections


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
    status: str = "open",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (section_id, title, status, 0, []),
        )
        return (await cursor.fetchone())[0]


async def fetch_section_row(db_pool, section_id: int) -> tuple:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT name, description, priority, status
            FROM hive.sections
            WHERE id = %s
            """,
            (section_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row


async def test_list_sections_empty(db_pool):
    assert await sections.list_sections() == []


async def test_list_sections_with_counts(db_pool):
    section_id = await insert_section(db_pool, name="Core", priority=4)
    await insert_task(db_pool, title="Open task", section_id=section_id, status="open")
    await insert_task(
        db_pool,
        title="In progress task",
        section_id=section_id,
        status="in_progress",
    )
    await insert_task(db_pool, title="Done task", section_id=section_id, status="done")
    await insert_task(db_pool, title="Blocked task", section_id=section_id, status="blocked")
    await insert_task(
        db_pool,
        title="Cancelled task",
        section_id=section_id,
        status="cancelled",
    )

    result = await sections.list_sections()

    assert result == [
        {
            "id": section_id,
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


async def test_list_sections_filter_by_status(db_pool):
    active_id = await insert_section(db_pool, name="Active", status="active")
    await insert_section(db_pool, name="Done", status="done")

    result = await sections.list_sections(status="active")

    assert [section["id"] for section in result] == [active_id]
    assert result[0]["status"] == "active"


async def test_list_sections_ordered_by_priority(db_pool):
    low_id = await insert_section(db_pool, name="Low", priority=1)
    high_id = await insert_section(db_pool, name="High", priority=9)
    mid_id = await insert_section(db_pool, name="Mid", priority=4)

    result = await sections.list_sections()

    assert [section["id"] for section in result] == [high_id, mid_id, low_id]


async def test_create_section_minimal(db_pool):
    section = await sections.create_section("Planning")
    row = await fetch_section_row(db_pool, section["id"])

    assert section == {
        "id": section["id"],
        "name": "Planning",
        "description": None,
        "priority": 0,
        "status": "active",
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Planning", None, 0, "active")


async def test_create_section_full(db_pool):
    section = await sections.create_section(
        "Execution",
        description="Implementation work",
        priority=8,
    )
    row = await fetch_section_row(db_pool, section["id"])

    assert section == {
        "id": section["id"],
        "name": "Execution",
        "description": "Implementation work",
        "priority": 8,
        "status": "active",
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Execution", "Implementation work", 8, "active")


async def test_update_section_fields(db_pool):
    section_id = await insert_section(db_pool, name="Old", description="Before", priority=1)

    section = await sections.update_section(
        section_id,
        name="New",
        priority=7,
        status="done",
    )
    row = await fetch_section_row(db_pool, section_id)

    assert section["id"] == section_id
    assert section["name"] == "New"
    assert section["description"] == "Before"
    assert section["priority"] == 7
    assert section["status"] == "done"
    assert row == ("New", "Before", 7, "done")


async def test_update_section_not_found(db_pool):
    with pytest.raises(ValueError, match="Section 9999 not found"):
        await sections.update_section(9999, name="Nope")
