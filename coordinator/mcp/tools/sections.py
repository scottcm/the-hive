from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool

SECTION_STATUSES = {"active", "done", "archived"}
SECTION_SELECT = """
    SELECT
        s.id,
        s.name,
        s.description,
        s.priority,
        s.status,
        COUNT(t.id) FILTER (WHERE t.status = 'open') AS open_count,
        COUNT(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_count,
        COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_count,
        COUNT(t.id) FILTER (WHERE t.status = 'blocked') AS blocked_count
    FROM hive.sections s
    LEFT JOIN hive.tasks t ON t.section_id = s.id
"""


def _serialize_section(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "priority": row["priority"],
        "status": row["status"],
        "task_counts": {
            "open": row["open_count"],
            "in_progress": row["in_progress_count"],
            "done": row["done_count"],
            "blocked": row["blocked_count"],
        },
    }


def _validate_section_status(status: str) -> None:
    if status not in SECTION_STATUSES:
        raise ValueError(f"Invalid status: {status}")


async def _fetch_section(section_id: int, conn: Any) -> dict[str, Any]:
    cursor = conn.cursor(row_factory=dict_row)
    await cursor.execute(
        f"""
        {SECTION_SELECT}
        WHERE s.id = %s
        GROUP BY s.id
        """,
        (section_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Section {section_id} not found")
    return _serialize_section(row)


async def list_sections(status: str | None = None) -> list[dict[str, Any]]:
    if status is not None:
        _validate_section_status(status)

    where_clause = ""
    params: list[Any] = []
    if status is not None:
        where_clause = "WHERE s.status = %s"
        params.append(status)

    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            f"""
            {SECTION_SELECT}
            {where_clause}
            GROUP BY s.id
            ORDER BY s.priority DESC, s.id
            """,
            params,
        )
        return [_serialize_section(row) for row in await cursor.fetchall()]


async def create_section(
    name: str,
    description: str | None = None,
    priority: int = 0,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                """
                INSERT INTO hive.sections (name, description, priority)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (name, description, priority),
            )
            row = await cursor.fetchone()
            assert row is not None
            return await _fetch_section(row["id"], conn)


async def update_section(
    section_id: int,
    name: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if status is not None:
        _validate_section_status(status)

    set_clauses = ["updated_at = now()"]
    params: list[Any] = []

    if name is not None:
        set_clauses.append("name = %s")
        params.append(name)
    if description is not None:
        set_clauses.append("description = %s")
        params.append(description)
    if priority is not None:
        set_clauses.append("priority = %s")
        params.append(priority)
    if status is not None:
        set_clauses.append("status = %s")
        params.append(status)

    params.append(section_id)

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                f"""
                UPDATE hive.sections
                SET {", ".join(set_clauses)}
                WHERE id = %s
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Section {section_id} not found")
            return await _fetch_section(section_id, conn)
