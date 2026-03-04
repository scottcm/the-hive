from coordinator.mcp.tools import sections


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
    status: str = "open",
) -> int:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO hive.tasks (section_id, title, status, priority, sequence_order, relevant_docs)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (section_id, title, status, 0, 0, []),
        )
        return (await cursor.fetchone())[0]


async def fetch_section_row(db_pool, section_id: int) -> tuple:
    async with db_pool.connection() as conn:
        cursor = await conn.execute(
            """
            SELECT name, description, priority, status, assigned_to
            FROM hive.sections
            WHERE id = %s
            """,
            (section_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        return row


async def test_list_sections_empty():
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
            "assigned_to": None,
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


async def test_create_section_minimal(db_pool):
    section = await sections.create_section("Planning")
    row = await fetch_section_row(db_pool, section["id"])

    assert section == {
        "id": section["id"],
        "name": "Planning",
        "description": None,
        "priority": 0,
        "status": "active",
        "assigned_to": None,
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Planning", None, 0, "active", None)


async def test_create_section_full(db_pool):
    section = await sections.create_section(
        "Execution",
        description="Implementation work",
        priority=8,
        assigned_to="codex",
    )
    row = await fetch_section_row(db_pool, section["id"])

    assert section == {
        "id": section["id"],
        "name": "Execution",
        "description": "Implementation work",
        "priority": 8,
        "status": "active",
        "assigned_to": "codex",
        "task_counts": {"open": 0, "in_progress": 0, "done": 0, "blocked": 0},
    }
    assert row == ("Execution", "Implementation work", 8, "active", "codex")


async def test_list_sections_ordered_by_priority(db_pool):
    low_id = await insert_section(db_pool, name="Low", priority=1)
    high_id = await insert_section(db_pool, name="High", priority=9)
    mid_id = await insert_section(db_pool, name="Mid", priority=4)

    result = await sections.list_sections()

    assert [section["id"] for section in result] == [high_id, mid_id, low_id]
