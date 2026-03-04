from typing import Any

from psycopg.rows import dict_row

from coordinator.db.connection import get_pool


def _serialize_section_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "priority": row["priority"],
        "status": row["status"],
        "assigned_to": row["assigned_to"],
        "task_counts": {
            "open": row["open_count"],
            "in_progress": row["in_progress_count"],
            "done": row["done_count"],
            "blocked": row["blocked_count"],
        },
    }


async def list_sections(status: str | None = None) -> list[dict[str, Any]]:
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
            SELECT
                s.id,
                s.name,
                s.description,
                s.priority,
                s.status,
                s.assigned_to,
                COUNT(t.id) FILTER (WHERE t.status = 'open') AS open_count,
                COUNT(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_count,
                COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_count,
                COUNT(t.id) FILTER (WHERE t.status = 'blocked') AS blocked_count
            FROM hive.sections s
            LEFT JOIN hive.tasks t ON t.section_id = s.id
            {where_clause}
            GROUP BY s.id
            ORDER BY s.priority DESC, s.id
            """,
            params,
        )
        return [_serialize_section_row(row) for row in await cursor.fetchall()]


async def create_section(
    name: str,
    description: str | None = None,
    priority: int = 0,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=dict_row)
        await cursor.execute(
            """
            INSERT INTO hive.sections (name, description, priority, assigned_to)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (name, description, priority, assigned_to),
        )
        row = await cursor.fetchone()
        assert row is not None
        section_id = row["id"]

        result_cursor = conn.cursor(row_factory=dict_row)
        await result_cursor.execute(
            """
            SELECT
                s.id,
                s.name,
                s.description,
                s.priority,
                s.status,
                s.assigned_to,
                0::bigint AS open_count,
                0::bigint AS in_progress_count,
                0::bigint AS done_count,
                0::bigint AS blocked_count
            FROM hive.sections s
            WHERE s.id = %s
            """,
            (section_id,),
        )
        row = await result_cursor.fetchone()
        assert row is not None
        return _serialize_section_row(row)
